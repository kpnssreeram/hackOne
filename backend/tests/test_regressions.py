"""Regression coverage for runtime paths that a syntax/build check cannot see."""
from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
import workflow
from agents import audio_director, supervisor, visual_director, voice_cameo, writer
import audio_mixer
from fixtures import FIXTURE_CONSTITUTION, FIXTURE_DNA, FIXTURE_PRODUCTION_SCRIPT, FIXTURE_VISIONS
from resilience import BreakerState, CircuitBreaker
from schemas import (
    ChangeRequest,
    ConstitutionCheck,
    ConstitutionReport,
    EpisodeFeedback,
    EpisodeStatus,
    SeriesPlan,
    StoryEpisode,
    VisualAsset,
    ProductionLine,
    ProductionScript,
    Session,
    VisionSelection,
    WorkflowStatus,
)


class WorkflowRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tempdir.name) / "sessions"
        self.sessions_dir.mkdir()
        self.original_sessions_dir = workflow.SESSIONS_DIR
        self.original_mode = workflow.NOLAN_MODE
        workflow.SESSIONS_DIR = self.sessions_dir
        workflow._sessions.clear()
        workflow._queues.clear()

    def tearDown(self):
        workflow.SESSIONS_DIR = self.original_sessions_dir
        workflow.NOLAN_MODE = self.original_mode
        workflow._sessions.clear()
        workflow._queues.clear()
        self.tempdir.cleanup()

    def _session(self) -> Session:
        return Session(
            id=str(uuid.uuid4()),
            status=WorkflowStatus.VISION_SELECTED,
            creative_dna=FIXTURE_DNA,
            visions=FIXTURE_VISIONS,
            selected_vision=VisionSelection(
                primary_vision_id="emotional_intimacy",
                opening_from="emotional_intimacy",
                relationship_from="emotional_intimacy",
                ending_from="emotional_intimacy",
            ),
        )

    def test_replay_stages_use_imported_fixtures_and_never_call_live_audio(self):
        workflow.NOLAN_MODE = "replay"

        async def live_audio_should_not_run(*_args, **_kwargs):
            raise AssertionError("Replay audio must not call a live provider")

        with patch.object(workflow, "generate_voice_lines", live_audio_should_not_run):
            dna = asyncio.run(workflow.run_dna_extraction("replay", "unused"))
            visions = asyncio.run(workflow.run_vision_generation("replay", dna))
            script = asyncio.run(workflow.run_script_generation(
                "replay",
                dna,
                VisionSelection(
                    primary_vision_id="emotional_intimacy",
                    opening_from="emotional_intimacy",
                    relationship_from="emotional_intimacy",
                    ending_from="emotional_intimacy",
                ),
                visions,
            ))
            report = asyncio.run(workflow.run_constitution_check("replay", dna, script))
            audio_url = asyncio.run(workflow.run_audio_render("replay", script))

        self.assertEqual(dna.protagonist.name, "Maya")
        self.assertEqual(len(visions), 3)
        self.assertEqual(script.title, FIXTURE_PRODUCTION_SCRIPT.title)
        self.assertEqual(report.overall_score, FIXTURE_CONSTITUTION.overall_score)
        self.assertEqual(audio_url, "")

    def test_failed_production_audio_stays_script_ready(self):
        workflow.NOLAN_MODE = "hybrid"
        session = self._session()
        workflow.save_session(session)

        async def script(*_args, **_kwargs):
            return FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)

        async def constitution(*_args, **_kwargs):
            return FIXTURE_CONSTITUTION.model_copy(deep=True)

        rendered_scripts = []

        async def no_audio(_session_id, script, *_args, **_kwargs):
            rendered_scripts.append(script)
            return ""

        with (
            patch.object(workflow, "run_script_generation", script),
            patch.object(workflow, "run_constitution_check", constitution),
            patch.object(workflow, "run_audio_render", no_audio),
        ):
            asyncio.run(workflow.run_produce_workflow(session.id))

        saved = workflow.load_session(session.id)
        self.assertIsNotNone(saved)
        self.assertIsNone(saved.audio_url)
        self.assertEqual(saved.status, WorkflowStatus.CONSTITUTION_DONE)
        self.assertEqual(rendered_scripts[0].title, FIXTURE_PRODUCTION_SCRIPT.title)

    def test_live_revision_accepts_changed_lines_and_applies_them(self):
        workflow.NOLAN_MODE = "hybrid"
        session = self._session()
        session.production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        session.status = WorkflowStatus.READY
        workflow.save_session(session)

        async def analysis(*_args, **_kwargs):
            return {
                "affected_scene_ids": ["line-12"],
                "preserved_elements": ["Maya's name"],
                "locked_elements": ["core emotion"],
                "impact_summary": "Made Karan threatening.",
                "changed_lines": [{
                    "line_index": 12,
                    "line": {
                        "type": "dialogue",
                        "character": "KARAN",
                        "text": "Find the phone before it finds you.",
                        "emotion": "cold warning",
                    },
                }],
            }

        async def constitution(*_args, **_kwargs):
            return FIXTURE_CONSTITUTION.model_copy(deep=True)

        rendered_scripts = []

        async def no_audio(_session_id, script, *_args, **_kwargs):
            rendered_scripts.append(script)
            return ""

        with (
            patch.object(workflow, "analyze_change_impact", analysis),
            patch.object(workflow, "run_constitution_check", constitution),
            patch.object(workflow, "run_audio_render", no_audio),
        ):
            asyncio.run(workflow.run_revision_workflow(
                session.id,
                ChangeRequest(change_instruction="Make Karan dangerous."),
            ))

        saved = workflow.load_session(session.id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.production_script.lines[12].text, "Find the phone before it finds you.")
        self.assertEqual(saved.creative_lock_diff.change_request, "Make Karan dangerous.")
        self.assertEqual(saved.status, WorkflowStatus.CONSTITUTION_DONE)
        self.assertEqual(rendered_scripts[0].lines[12].text, "Find the phone before it finds you.")

    def test_replay_revision_replaces_fixture_lines_before_rendering(self):
        workflow.NOLAN_MODE = "replay"
        session = self._session()
        session.production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        session.status = WorkflowStatus.READY
        workflow.save_session(session)

        async def no_audio(*_args, **_kwargs):
            return ""

        with patch.object(workflow, "run_audio_render", no_audio):
            asyncio.run(workflow.run_revision_workflow(
                session.id,
                ChangeRequest(change_instruction="Make Karan dangerous."),
            ))

        saved = workflow.load_session(session.id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.production_script.lines[12].text, "I see you, Maya. I am the only one who does.")
        self.assertEqual(saved.production_script.lines[16].character, "KARAN")

    def test_audio_render_uses_selected_language_or_detected_language(self):
        """The session's language must reach the voice renderer, not just the writer."""
        workflow.NOLAN_MODE = "hybrid"
        session = self._session()
        session.preferences.output_language = "hi"
        session.detected_input_language = "te"
        workflow.save_session(session)
        rendered_languages: list[str | None] = []

        async def fake_voice_lines(*_args, language=None, **_kwargs):
            rendered_languages.append(language)
            return []

        def fake_mix(_timeline, out_path):
            out_path.write_bytes(b"mp3")

        with (
            patch.object(workflow, "generate_voice_lines", fake_voice_lines),
            patch.object(workflow, "mix_timeline", fake_mix),
        ):
            asyncio.run(workflow.run_audio_render(session.id, FIXTURE_PRODUCTION_SCRIPT))
            session.preferences.output_language = "auto"
            workflow.save_session(session)
            asyncio.run(workflow.run_audio_render(session.id, FIXTURE_PRODUCTION_SCRIPT))

        # A creator's selection wins; auto uses the detected spoken language.
        self.assertEqual(rendered_languages, ["hi", "te"])


class SeriesWorkflowRegressionTests(unittest.TestCase):
    """The series path must remain confirmation-first and continuity-safe."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tempdir.name) / "sessions"
        self.sessions_dir.mkdir()
        self.original_sessions_dir = workflow.SESSIONS_DIR
        self.original_mode = workflow.NOLAN_MODE
        workflow.SESSIONS_DIR = self.sessions_dir
        workflow._sessions.clear()
        workflow._queues.clear()

    def tearDown(self):
        workflow.SESSIONS_DIR = self.original_sessions_dir
        workflow.NOLAN_MODE = self.original_mode
        workflow._sessions.clear()
        workflow._queues.clear()
        self.tempdir.cleanup()

    def _session(self) -> Session:
        return Session(
            id=str(uuid.uuid4()),
            status=WorkflowStatus.VISIONS_READY,
            creative_dna=FIXTURE_DNA,
            visions=FIXTURE_VISIONS,
            selected_vision=VisionSelection(
                primary_vision_id="emotional_intimacy",
                opening_from="emotional_intimacy",
                relationship_from="emotional_intimacy",
                ending_from="emotional_intimacy",
            ),
        )

    def _with_series(self) -> Session:
        session = self._session()
        plan = writer._fallback_series_plan(FIXTURE_DNA, FIXTURE_VISIONS[1])
        session.series_plan = plan
        session.episodes = [StoryEpisode(number=item.number, outline=item) for item in plan.episode_outlines]
        return session

    def test_series_outline_creates_three_outlined_episodes_without_media(self):
        workflow.NOLAN_MODE = "replay"
        session = self._session()
        workflow.save_session(session)

        async def audio_must_not_run(*_args, **_kwargs):
            raise AssertionError("Planning a series must not render audio")

        with patch.object(workflow, "run_audio_render", audio_must_not_run):
            asyncio.run(workflow.run_series_outline(session.id))

        saved = workflow.load_session(session.id)
        self.assertIsNotNone(saved.series_plan)
        self.assertEqual([episode.number for episode in saved.episodes], [1, 2, 3])
        self.assertTrue(all(episode.status == EpisodeStatus.OUTLINED for episode in saved.episodes))
        self.assertTrue(all(episode.audio_url is None for episode in saved.episodes))
        self.assertEqual(saved.status, WorkflowStatus.VISIONS_READY)

    def test_draft_remains_credit_free_until_creator_confirms_it(self):
        workflow.NOLAN_MODE = "hybrid"
        session = self._with_series()
        workflow.save_session(session)
        rendered: list[dict] = []

        async def script(*_args, **_kwargs):
            return FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)

        async def constitution(*_args, **_kwargs):
            return FIXTURE_CONSTITUTION.model_copy(deep=True)

        async def audio(_session_id, _script, *_args, **kwargs):
            rendered.append(kwargs)
            return f"/audio/{session.id}/episode_01.mp3"

        with (
            patch.object(workflow, "run_script_generation", script),
            patch.object(workflow, "run_constitution_check", constitution),
            patch.object(workflow, "run_audio_render", audio),
        ):
            asyncio.run(workflow.run_episode_draft(session.id, 1))
            after_draft = workflow.load_session(session.id)
            self.assertEqual(after_draft.episodes[0].status, EpisodeStatus.DRAFT_READY)
            self.assertIsNone(after_draft.episodes[0].audio_url)
            self.assertEqual(rendered, [])

            asyncio.run(workflow.run_confirmed_episode_render(session.id, 1))

        saved = workflow.load_session(session.id)
        self.assertEqual(rendered, [{"episode_number": 1}])
        self.assertEqual(saved.episodes[0].status, EpisodeStatus.READY)
        self.assertEqual(saved.episodes[0].audio_url, f"/audio/{session.id}/episode_01.mp3")
        self.assertEqual(saved.audio_url, saved.episodes[0].audio_url)
        self.assertEqual(saved.status, WorkflowStatus.READY)

    def test_revision_stales_unapproved_future_work_without_overwriting_approved_history(self):
        workflow.NOLAN_MODE = "hybrid"
        session = self._with_series()
        first, second, third = session.episodes
        first.status = EpisodeStatus.READY
        first.production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        first.audio_url = "/audio/old/episode_01.mp3"
        second.status = EpisodeStatus.DRAFT_READY
        second.production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        second.constitution_report = FIXTURE_CONSTITUTION.model_copy(deep=True)
        second.audio_url = "/audio/old/episode_02.mp3"
        third.status = EpisodeStatus.OUTLINED
        workflow.save_session(session)

        async def analysis(*_args, **_kwargs):
            return {
                "changed_lines": [{
                    "line_index": 12,
                    "line": {
                        "type": "dialogue",
                        "character": "KARAN",
                        "text": "Do not answer the next call.",
                        "emotion": "urgent",
                    },
                }],
            }

        async def constitution(*_args, **_kwargs):
            return FIXTURE_CONSTITUTION.model_copy(deep=True)

        with (
            patch.object(workflow, "analyze_change_impact", analysis),
            patch.object(workflow, "run_constitution_check", constitution),
        ):
            asyncio.run(workflow.run_episode_revision(
                session.id,
                1,
                EpisodeFeedback(change_this_episode="Make the final warning more urgent."),
            ))

        saved = workflow.load_session(session.id)
        self.assertEqual(saved.episodes[0].status, EpisodeStatus.DRAFT_READY)
        self.assertEqual(saved.episodes[0].production_script.lines[12].text, "Do not answer the next call.")
        self.assertIsNone(saved.episodes[0].audio_url)
        self.assertEqual(saved.episodes[1].status, EpisodeStatus.STALE)
        self.assertIsNone(saved.episodes[1].production_script)
        self.assertIsNone(saved.episodes[1].constitution_report)
        self.assertIsNone(saved.episodes[1].audio_url)
        self.assertEqual(saved.episodes[2].status, EpisodeStatus.STALE)

    def test_approved_episode_feedback_is_carried_only_into_the_next_draft(self):
        session = self._with_series()
        first = session.episodes[0]
        first.status = EpisodeStatus.READY
        first.production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        workflow.save_session(session)
        drafts: list[int] = []

        async def next_draft(_session_id, episode_number):
            drafts.append(episode_number)

        feedback = EpisodeFeedback(
            keep="Keep Maya and Karan's closeness.",
            next_direction="Make Episode 2 more dangerous.",
        )
        with patch.object(workflow, "run_episode_draft", next_draft):
            asyncio.run(workflow.run_continue_series(session.id, 1, feedback))

        saved = workflow.load_session(session.id)
        self.assertEqual(saved.episodes[0].status, EpisodeStatus.APPROVED)
        self.assertEqual(saved.episodes[0].feedback, feedback)
        self.assertIn("Episode 1", saved.episodes[0].continuity_summary)
        self.assertEqual(drafts, [2])

    def test_episode_audio_keeps_the_selected_language_and_its_own_file(self):
        workflow.NOLAN_MODE = "hybrid"
        session = self._session()
        session.preferences.output_language = "te"
        workflow.save_session(session)
        languages: list[str | None] = []

        async def voice_lines(*_args, language=None, **_kwargs):
            languages.append(language)
            return []

        def mix(_timeline, out_path):
            out_path.write_bytes(b"mp3")

        with (
            patch.object(workflow, "generate_voice_lines", voice_lines),
            patch.object(workflow, "mix_timeline", mix),
        ):
            url = asyncio.run(workflow.run_audio_render(
                session.id,
                FIXTURE_PRODUCTION_SCRIPT,
                episode_number=2,
            ))

        self.assertEqual(languages, ["te"])
        self.assertEqual(url, f"/audio/{session.id}/episode_02.mp3")
        self.assertTrue((self.sessions_dir / session.id / "audio" / "episode_02.mp3").exists())


class SeriesSchemaRegressionTests(unittest.TestCase):
    def test_series_plan_rejects_duplicate_or_out_of_order_episode_numbers(self):
        plan = writer._fallback_series_plan(FIXTURE_DNA, FIXTURE_VISIONS[1])
        malformed = plan.model_dump()
        malformed["episode_outlines"][1]["number"] = 1

        with self.assertRaises(ValidationError):
            SeriesPlan.model_validate(malformed)

        with self.assertRaises(ValidationError):
            StoryEpisode(number=2, outline=plan.episode_outlines[0])


class SupervisorRegressionTests(unittest.TestCase):
    def test_normalizes_swapped_rules_and_ignores_silence_for_dialogue_only_narration_check(self):
        script = ProductionScript(
            title="No voice-over",
            estimated_duration_seconds=12,
            lines=[
                ProductionLine(type="dialogue", character="MAYA", text="Don't hang up.", emotion="afraid"),
                ProductionLine(type="silence", duration_seconds=1.0),
                ProductionLine(type="dialogue", character="KARAN", text="You already did.", emotion="calm"),
            ],
        )
        malformed = ConstitutionReport(
            overall_score=88,
            checks=[
                ConstitutionCheck(
                    rule_number=5,
                    rule="Minimal narration",
                    passed=False,
                    evidence="Silence after Maya's line.",
                    reason="The pause needs background ambience.",
                    repair="[AMBIENCE: intensifying wind]",
                ),
                ConstitutionCheck(
                    rule_number=6,
                    rule="Every sound cue has narrative purpose",
                    passed=True,
                    evidence="The silence creates suspense.",
                ),
            ],
        )

        normalized = supervisor._normalize_constitution_report(malformed, script)

        self.assertEqual([check.rule_number for check in normalized.checks], list(range(1, 9)))
        self.assertEqual(
            [check.rule for check in normalized.checks],
            list(supervisor.CANONICAL_RULES.values()),
        )
        self.assertTrue(normalized.checks[4].passed)  # Sound purpose stays Rule 5.
        narration = normalized.checks[5]
        self.assertTrue(narration.passed)
        self.assertEqual(narration.rule, "Narration economy")
        self.assertIn("No narrator", narration.evidence)
        self.assertIsNone(narration.reason)
        self.assertIsNone(narration.repair)

    def test_final_episode_checks_an_earned_ending_instead_of_a_fake_cliffhanger(self):
        script = ProductionScript(
            title="The Choice",
            estimated_duration_seconds=90,
            lines=[
                ProductionLine(type="ambience", description="Rain fades after the final call", duration_seconds=2),
                ProductionLine(type="dialogue", character="MAYA", text="Karan, I remember you. I choose to live with the truth.", emotion="tearful resolve"),
                ProductionLine(type="sfx", description="The phone line goes quiet, peacefully", duration_seconds=1),
                ProductionLine(type="dialogue", character="MAYA", text="I choose to remember, and I am finally home.", emotion="quiet certainty"),
            ],
        )

        report = supervisor._dynamic_constitution_fallback(script, FIXTURE_DNA, episode_number=3)
        ending = next(check for check in report.checks if check.rule_number == 7)

        self.assertEqual(ending.rule, "Ending payoff")
        self.assertTrue(ending.passed)


class VisualPlanningRegressionTests(unittest.TestCase):
    def test_asset_aware_fallback_uses_real_media_and_place_reference_without_video_generation(self):
        assets = [
            VisualAsset(id="photo", kind="photo", filename="family.jpg", url="/media/family.jpg", consented=True),
            VisualAsset(id="clip", kind="video", filename="street.mp4", url="/media/street.mp4", consented=True),
            VisualAsset(id="place", kind="place_reference", filename="station.jpg", url="/media/station.jpg", consented=True),
        ]

        plan = visual_director.fallback_plan(FIXTURE_DNA, FIXTURE_PRODUCTION_SCRIPT, assets)

        self.assertEqual(sum(beat.duration_seconds for beat in plan.beats), 90)
        self.assertEqual(plan.beats[0].kind, "user_video")
        self.assertEqual(plan.beats[0].source_asset, "street.mp4")
        self.assertEqual(plan.beats[1].kind, "portrait_card")
        self.assertEqual(plan.beats[1].source_asset, "family.jpg")
        self.assertTrue(any(beat.source_asset == "station.jpg" for beat in plan.beats))


class ApiSecurityRegressionTests(unittest.TestCase):
    def test_audio_route_rejects_session_path_traversal(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / ".env").write_text("must-not-be-served")
            original_sessions_dir = main.SESSIONS_DIR
            main.SESSIONS_DIR = root / "sessions"
            try:
                response = TestClient(main.app).get("/audio/%2E%2E/.env")
            finally:
                main.SESSIONS_DIR = original_sessions_dir

        self.assertEqual(response.status_code, 400)

    def test_produce_requires_generated_valid_visions(self):
        with tempfile.TemporaryDirectory() as tempdir:
            original_sessions_dir = workflow.SESSIONS_DIR
            original_sessions = workflow._sessions.copy()
            workflow.SESSIONS_DIR = Path(tempdir) / "sessions"
            workflow.SESSIONS_DIR.mkdir()
            workflow._sessions.clear()
            try:
                empty_session = Session(id=str(uuid.uuid4()))
                workflow.save_session(empty_session)
                selection = {
                    "vision_selection": {
                        "primary_vision_id": "not-generated",
                        "opening_from": "not-generated",
                        "relationship_from": "not-generated",
                        "ending_from": "not-generated",
                    }
                }
                client = TestClient(main.app)
                missing_visions = client.post(f"/api/sessions/{empty_session.id}/produce", json=selection)

                ready_session = Session(
                    id=str(uuid.uuid4()),
                    status=WorkflowStatus.VISIONS_READY,
                    creative_dna=FIXTURE_DNA,
                    visions=FIXTURE_VISIONS,
                )
                workflow.save_session(ready_session)
                invalid_selection = client.post(f"/api/sessions/{ready_session.id}/produce", json=selection)
            finally:
                workflow.SESSIONS_DIR = original_sessions_dir
                workflow._sessions.clear()
                workflow._sessions.update(original_sessions)

        self.assertEqual(missing_visions.status_code, 409)
        self.assertEqual(invalid_selection.status_code, 422)


class SeriesApiRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tempdir.name) / "sessions"
        self.sessions_dir.mkdir()
        self.original_workflow_dir = workflow.SESSIONS_DIR
        self.original_main_dir = main.SESSIONS_DIR
        self.original_sessions = workflow._sessions.copy()
        workflow.SESSIONS_DIR = self.sessions_dir
        main.SESSIONS_DIR = self.sessions_dir
        workflow._sessions.clear()

    def tearDown(self):
        workflow.SESSIONS_DIR = self.original_workflow_dir
        main.SESSIONS_DIR = self.original_main_dir
        workflow._sessions.clear()
        workflow._sessions.update(self.original_sessions)
        self.tempdir.cleanup()

    @staticmethod
    def _selection() -> dict:
        return {
            "vision_selection": {
                "primary_vision_id": "emotional_intimacy",
                "opening_from": "emotional_intimacy",
                "relationship_from": "emotional_intimacy",
                "ending_from": "emotional_intimacy",
            },
        }

    def test_new_series_clears_a_previous_pilot_before_background_planning(self):
        session = Session(
            id=str(uuid.uuid4()),
            status=WorkflowStatus.VISIONS_READY,
            creative_dna=FIXTURE_DNA,
            visions=FIXTURE_VISIONS,
            production_script=FIXTURE_PRODUCTION_SCRIPT,
            constitution_report=FIXTURE_CONSTITUTION,
            audio_url="/audio/old/pilot.mp3",
            cover_image_url="/media/old/episode-cover.png",
        )
        workflow.save_session(session)
        planned: list[str] = []

        async def outline(session_id: str):
            planned.append(session_id)

        with patch.object(main, "run_series_outline", outline):
            response = TestClient(main.app).post(
                f"/api/sessions/{session.id}/series",
                json=self._selection(),
            )

        saved = workflow.load_session(session.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(planned, [session.id])
        self.assertEqual(saved.status, WorkflowStatus.VISION_SELECTED)
        self.assertIsNone(saved.production_script)
        self.assertIsNone(saved.constitution_report)
        self.assertIsNone(saved.audio_url)
        self.assertIsNone(saved.cover_image_url)

    def test_episode_revision_requires_a_real_change_and_preserves_approved_continuity(self):
        plan = writer._fallback_series_plan(FIXTURE_DNA, FIXTURE_VISIONS[1])
        first, second, third = [StoryEpisode(number=item.number, outline=item) for item in plan.episode_outlines]
        first.status = EpisodeStatus.READY
        first.production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        second.status = EpisodeStatus.APPROVED
        third.status = EpisodeStatus.OUTLINED
        session = Session(
            id=str(uuid.uuid4()),
            status=WorkflowStatus.READY,
            creative_dna=FIXTURE_DNA,
            series_plan=plan,
            episodes=[first, second, third],
        )
        workflow.save_session(session)
        client = TestClient(main.app)

        empty_revision = client.post(
            f"/api/sessions/{session.id}/episodes/1/feedback",
            json={"action": "revise", "feedback": {"change_this_episode": ""}},
        )
        retroactive_revision = client.post(
            f"/api/sessions/{session.id}/episodes/1/feedback",
            json={"action": "revise", "feedback": {"change_this_episode": "Change the ending."}},
        )

        self.assertEqual(empty_revision.status_code, 422)
        self.assertEqual(retroactive_revision.status_code, 409)

    def test_episode_endpoints_reserve_draft_and_render_work_before_background_runs(self):
        plan = writer._fallback_series_plan(FIXTURE_DNA, FIXTURE_VISIONS[1])
        episode = StoryEpisode(number=1, outline=plan.episode_outlines[0])
        session = Session(
            id=str(uuid.uuid4()),
            status=WorkflowStatus.VISIONS_READY,
            creative_dna=FIXTURE_DNA,
            series_plan=plan,
            episodes=[episode],
        )
        workflow.save_session(session)
        client = TestClient(main.app)

        async def leave_draft_pending(*_args, **_kwargs):
            return None

        with patch.object(main, "run_episode_draft", leave_draft_pending):
            drafted = client.post(f"/api/sessions/{session.id}/episodes/1/draft")
            duplicate_draft = client.post(f"/api/sessions/{session.id}/episodes/1/draft")

        reserved = workflow.load_session(session.id)
        self.assertEqual(drafted.status_code, 200)
        self.assertEqual(duplicate_draft.status_code, 409)
        self.assertEqual(reserved.episodes[0].status, EpisodeStatus.DRAFTING)
        self.assertEqual(reserved.status, WorkflowStatus.SCRIPT_DRAFTED)

        reserved.episodes[0].status = EpisodeStatus.DRAFT_READY
        reserved.episodes[0].production_script = FIXTURE_PRODUCTION_SCRIPT.model_copy(deep=True)
        workflow.update_status(reserved, WorkflowStatus.CONSTITUTION_DONE)

        async def leave_render_pending(*_args, **_kwargs):
            return None

        with patch.object(main, "run_confirmed_episode_render", leave_render_pending):
            confirmed = client.post(f"/api/sessions/{session.id}/episodes/1/confirm")
            duplicate_confirm = client.post(f"/api/sessions/{session.id}/episodes/1/confirm")

        reserved = workflow.load_session(session.id)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(duplicate_confirm.status_code, 409)
        self.assertEqual(reserved.episodes[0].status, EpisodeStatus.RENDERING)
        self.assertEqual(reserved.status, WorkflowStatus.AUDIO_RENDERING)

    def test_story_asset_upload_requires_safe_media_extension_and_records_consent(self):
        session = Session(id=str(uuid.uuid4()))
        workflow.save_session(session)
        client = TestClient(main.app)

        unsafe = client.post(
            f"/api/sessions/{session.id}/story-assets",
            files={"asset": ("photo.html", b"not-html", "image/png")},
            data={"kind": "photo", "consent": "true"},
        )
        accepted = client.post(
            f"/api/sessions/{session.id}/story-assets",
            files={"asset": ("station.webp", b"image-bytes", "image/webp")},
            data={"kind": "place_reference", "consent": "true"},
        )

        saved = workflow.load_session(session.id)
        self.assertEqual(unsafe.status_code, 422)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(len(saved.visual_assets), 1)
        self.assertEqual(saved.visual_assets[0].kind, "place_reference")
        self.assertTrue(saved.visual_assets[0].consented)
        self.assertTrue((self.sessions_dir / session.id / "visual" / saved.visual_assets[0].filename).exists())


class CoverImageRegressionTests(unittest.TestCase):
    def test_cover_image_is_persisted_served_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tempdir:
            sessions_dir = Path(tempdir) / "sessions"
            sessions_dir.mkdir()
            original_workflow_dir = workflow.SESSIONS_DIR
            original_main_dir = main.SESSIONS_DIR
            original_sessions = workflow._sessions.copy()
            workflow.SESSIONS_DIR = sessions_dir
            main.SESSIONS_DIR = sessions_dir
            workflow._sessions.clear()
            try:
                session = Session(
                    id=str(uuid.uuid4()),
                    status=WorkflowStatus.READY,
                    creative_dna=FIXTURE_DNA,
                    production_script=FIXTURE_PRODUCTION_SCRIPT,
                )
                workflow.save_session(session)

                async def generated_cover(*_args, **_kwargs):
                    return b"png-cover-bytes"

                with patch.object(main, "generate_episode_cover", generated_cover):
                    client = TestClient(main.app)
                    response = client.post(f"/api/sessions/{session.id}/cover-image")
                    media = client.get(response.json()["url"])

                async def unavailable_cover(*_args, **_kwargs):
                    return None

                with patch.object(main, "generate_episode_cover", unavailable_cover):
                    fallback_response = client.post(f"/api/sessions/{session.id}/cover-image")
                    fallback_media = client.get(fallback_response.json()["url"])

                saved = workflow.load_session(session.id)
            finally:
                workflow.SESSIONS_DIR = original_workflow_dir
                main.SESSIONS_DIR = original_main_dir
                workflow._sessions.clear()
                workflow._sessions.update(original_sessions)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["generated"])
        self.assertEqual(response.json()["url"], f"/media/{session.id}/episode-cover.png")
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.content, b"png-cover-bytes")
        self.assertEqual(fallback_response.status_code, 200)
        self.assertFalse(fallback_response.json()["generated"])
        self.assertEqual(fallback_response.json()["url"], f"/media/{session.id}/episode-cover.svg")
        self.assertEqual(fallback_media.status_code, 200)
        self.assertIn(b"<svg", fallback_media.content)
        self.assertEqual(saved.cover_image_url, fallback_response.json()["url"])


class AudioMixerRegressionTests(unittest.TestCase):
    def test_mixer_ends_at_the_final_sfx_without_ambience_padding(self):
        """The rendered file must keep the final SFX beat, not add a bed tail."""
        from pydub.generators import Sine

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            line_path = root / "line.mp3"
            sfx_path = root / "sting.mp3"
            output_path = root / "pilot.mp3"

            self.assertTrue(audio_mixer._configure_ffmpeg())
            with line_path.open("wb") as line_file:
                Sine(440).to_audio_segment(duration=1_000).export(line_file, format="mp3")
            with sfx_path.open("wb") as sfx_file:
                Sine(880).to_audio_segment(duration=700).export(sfx_file, format="mp3")
            audio_mixer.mix_timeline([
                {"type": "ambience", "description": "wind"},
                {"type": "dialogue", "path": str(line_path), "pause_after": 0.4},
                {"type": "sfx", "description": "final sting", "path": str(sfx_path)},
            ], output_path)
            mixed = audio_mixer._decode_mp3(output_path)

        # Dialogue + explicit pause + final SFX + its short cue gap.
        self.assertGreaterEqual(len(mixed), 2_100)
        self.assertLess(len(mixed), 3_000)


class AudioLanguageRegressionTests(unittest.TestCase):
    def test_writer_uses_clear_hindi_and_telugu_dialogue_instructions(self):
        self.assertIn("Hindi (Devanagari)", writer._dialogue_language_instruction("hi"))
        self.assertIn("Telugu", writer._dialogue_language_instruction("te"))

    def test_hindi_and_telugu_use_explicit_voice_language_with_delivery_settings(self):
        calls: list[dict] = []

        async def audio_chunks():
            yield b"spoken"

        class FakeTextToSpeech:
            def convert(self, **kwargs):
                calls.append(kwargs)
                return audio_chunks()

        fake_client = type("Client", (), {"text_to_speech": FakeTextToSpeech()})()
        with patch.object(audio_director, "el", fake_client):
            hindi, _ = asyncio.run(audio_director.synthesise_line(
                "MAYA", "मुझे अब सच बताना होगा।", "voice close to breaking",
                None, None, "devastated", {"MAYA": "auto:feminine"}, language="hi",
            ))
            telugu, _ = asyncio.run(audio_director.synthesise_line(
                "MAYA", "నిజం ఇప్పుడు చెప్పాలి.", "breathless", None, None,
                "urgent", {"MAYA": "auto:feminine"}, language="te",
            ))

        self.assertEqual((hindi, telugu), (b"spoken", b"spoken"))
        self.assertEqual(calls[0]["model_id"], audio_director.STABLE_MODEL)
        self.assertNotIn("language_code", calls[0])
        self.assertEqual(calls[1]["model_id"], audio_director.EXPRESSIVE_MODEL)
        self.assertEqual(calls[1]["language_code"], "te")
        self.assertTrue(calls[1]["text"].startswith("[breathless, urgent]"))
        self.assertEqual(calls[0]["voice_settings"].style, 0.92)
        self.assertEqual(calls[1]["voice_settings"].style, 0.78)

    def test_stock_voice_fallback_keeps_hindi_and_emotion_direction(self):
        calls: dict[str, dict] = {}

        class BrokenTextToSpeech:
            def convert(self, **_kwargs):
                raise RuntimeError("voice unavailable")

        class FakeSpeech:
            async def create(self, **kwargs):
                calls["speech"] = kwargs
                return type("Speech", (), {"content": b"fallback"})()

        fake_eleven = type("Client", (), {"text_to_speech": BrokenTextToSpeech()})()
        fake_openai = type("Client", (), {"audio": type("Audio", (), {"speech": FakeSpeech()})()})()
        with (
            patch.object(audio_director, "el", fake_eleven),
            patch.object(audio_director, "oai_tts", fake_openai),
        ):
            audio, _ = asyncio.run(audio_director.synthesise_line(
                "MAYA", "मुझे डर लग रहा है।", "whispering", None, None,
                "afraid", {"MAYA": "auto:feminine"}, language="Hindi",
            ))

        instructions = calls["speech"]["extra_body"]["instructions"]
        self.assertEqual(audio, b"fallback")
        self.assertIn("Hindi", instructions)
        self.assertIn("whispering", instructions)
        self.assertIn("afraid", instructions)


class VoiceCameoRegressionTests(unittest.TestCase):
    def test_clone_and_preview_use_the_async_sdk_surfaces(self):
        calls: dict[str, object] = {}

        class FakeVoices:
            async def add(self, **kwargs):
                calls["add"] = kwargs
                return type("Clone", (), {"voice_id": "voice-123", "requires_verification": False})()

        async def chunks():
            yield b"preview-"
            yield b"bytes"

        class FakeTextToSpeech:
            def convert(self, **kwargs):
                calls["convert"] = kwargs
                return chunks()

        fake_client = type("Client", (), {
            "voices": FakeVoices(),
            "text_to_speech": FakeTextToSpeech(),
        })()

        with patch.object(voice_cameo, "el", fake_client):
            voice_id, needs_verification = asyncio.run(voice_cameo.clone_voice(b"sample", "session-id"))
            preview = asyncio.run(voice_cameo.preview_cameo("voice-123"))

        self.assertEqual((voice_id, needs_verification), ("voice-123", False))
        self.assertIn("add", calls)
        self.assertEqual(calls["add"]["name"], "nolan-cameo-session-")
        self.assertEqual(preview, b"preview-bytes")
        self.assertIn("convert", calls)

    def test_clone_explains_when_instant_voice_cloning_needs_an_upgrade(self):
        class FakeVoices:
            async def add(self, **_kwargs):
                raise RuntimeError("payment_required: paid_plan_required")

        fake_client = type("Client", (), {"voices": FakeVoices()})()

        with patch.object(voice_cameo, "el", fake_client):
            with self.assertRaises(voice_cameo.VoiceClonePlanRequired):
                asyncio.run(voice_cameo.clone_voice(b"sample", "session-id"))


class ResilienceRegressionTests(unittest.TestCase):
    def test_failed_half_open_probe_reopens_the_breaker(self):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=1)
        breaker.record_failure()
        breaker._state = BreakerState.HALF_OPEN
        breaker._opened_at = None

        breaker.record_failure()

        self.assertEqual(breaker._state, BreakerState.OPEN)
        self.assertIsNotNone(breaker._opened_at)


if __name__ == "__main__":
    unittest.main()
