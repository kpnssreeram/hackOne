"""
Hackathon SSL shim — corporate Cisco Umbrella proxy intercepts TLS, so Python's
certifi bundle can't verify api.openai.com / api.elevenlabs.io.
This forces every httpx client (used by both OpenAI and ElevenLabs SDKs) to skip
verification. Import this FIRST, before any SDK client is constructed.
"""
import warnings
import httpx

warnings.filterwarnings("ignore")

for _cls in (httpx.AsyncClient, httpx.Client):
    _orig = _cls.__init__

    def _make(orig):
        def __init__(self, *args, **kwargs):
            kwargs["verify"] = False
            orig(self, *args, **kwargs)
        return __init__

    _cls.__init__ = _make(_orig)
