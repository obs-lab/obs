from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import voice
from auth_routes import current_user

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str
    voice: str = ""
    lang: str = ""


@router.get("/status")
def voice_status(user: dict = Depends(current_user)):
    return voice.status()


@router.get("/voices")
def voice_catalogue(user: dict = Depends(current_user)):
    return {
        "engine": voice.tts_engine_available(),
        "voices": voice.available_voices(),
        "default_lang": voice.TTS_DEFAULT_LANG,
    }


@router.post("/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = Form(""),
    user: dict = Depends(current_user),
):
    payload = await file.read()
    try:
        return voice.transcribe(payload, file.filename or "audio.webm", language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Trascrizione fallita: " + str(exc))


@router.post("/speak")
def voice_speak(req: SpeakRequest, user: dict = Depends(current_user)):
    try:
        result = voice.synthesize(req.text, req.voice, req.lang)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Sintesi fallita: " + str(exc))
    return Response(
        content=result["audio"],
        media_type="audio/wav",
        headers={
            "Content-Disposition": "inline; filename=obs_voice.wav",
            "X-OBS-Voice-Lang": result["lang"],
            "X-OBS-Voice-Detected": result["detected"],
            "X-OBS-Voice-Name": result["voice"],
        },
    )
