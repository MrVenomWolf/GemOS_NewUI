import base64
import re
import time
from typing import List, Dict, Any, Generator, Optional
from google import genai
from google.genai import types

# Fallback list only used if no API key is configured yet or network is offline
FALLBACK_MODELS = [
    {"id": "gemini-4-argon", "name": "Gemini 4 Argon", "badge": "LATEST"},
    {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash", "badge": "FAST"},
    {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash", "badge": "FAST"},
    {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash", "badge": "FAST"},
    {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash", "badge": "FAST"},
    {"id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro Preview", "badge": "PRO"},
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "badge": "PRO"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "badge": "STABLE"},
    {"id": "gemini-nano-banana-2.1", "name": "Gemini Nano Banana 2.1", "badge": "IMAGE"},
    {"id": "nano-banana-pro-preview", "name": "Nano Banana Pro Preview", "badge": "IMAGE"},
    {"id": "gemini-2.5-flash-image", "name": "Gemini 2.5 Flash Image", "badge": "IMAGE"},
]


def is_image_model(model_id: str) -> bool:
    m = (model_id or "").lower()
    return "image" in m or "banana" in m or "imagen" in m


def is_image_generation_prompt(text: str) -> bool:
    t = (text or "").lower()
    if "nanobanana" in t or "nano banana" in t or "nano-banana" in t:
        return True
    return bool(
        re.search(
            r"\b(generate|create|draw|paint|render|make|design|sketch|illustrate)\b[\s\S]{0,45}\b(image|picture|photo|art|wallpaper|logo|illustration|icon|poster|avatar|drawing)\b",
            t,
        )
    )


def _model_sort_key(model_item: Dict[str, Any]) -> tuple:
    """Sort models so the newest Gemini versions appear at the top, followed immediately by Nano Banana / Image models."""
    mid = model_item["id"].lower()
    ver_match = re.search(r"gemini-(\d+(?:\.\d+)?)", mid)
    ver = float(ver_match.group(1)) if ver_match else 0.0

    if not ver and "banana" in mid:
        b_match = re.search(r"(\d+(?:\.\d+)?)", mid)
        ver = float(b_match.group(1)) if b_match else 3.0

    is_img = is_image_model(mid)
    is_core_gemini = (
        2
        if (mid.startswith("gemini-") and not any(x in mid for x in ("tts", "image", "transcribe", "robotics", "banana", "live", "audio")))
        else (1 if is_img else 0)
    )
    is_argon_or_pro = 1 if ("argon" in mid or "pro" in mid or "banana" in mid) else 0
    return (is_core_gemini, ver, is_argon_or_pro, mid)


class GeminiService:
    def __init__(self):
        self._clients: Dict[str, genai.Client] = {}
        self._models_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_ttl = 300.0  # 5 minutes auto-refresh cache

    def _get_client(self, api_key: str) -> genai.Client:
        if not api_key:
            raise ValueError("No Gemini API key configured. Open Settings (Ctrl+,) to add your key.")
        if api_key not in self._clients:
            self._clients[api_key] = genai.Client(api_key=api_key)
        return self._clients[api_key]

    def list_available_models(self, api_key: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Dynamically fetch and sort all available generateContent models from Google AI Studio."""
        if not api_key:
            return FALLBACK_MODELS

        now = time.time()
        if not force_refresh and api_key in self._models_cache:
            cached_time, cached_list = self._models_cache[api_key]
            if now - cached_time < self._cache_ttl and cached_list:
                return cached_list

        try:
            client = self._get_client(api_key)
            raw_models = list(client.models.list())
            discovered: List[Dict[str, Any]] = []
            seen_ids = set()

            for m in raw_models:
                raw_name = getattr(m, "name", "") or ""
                model_id = raw_name.replace("models/", "").strip()
                if not model_id or model_id in seen_ids:
                    continue

                actions = getattr(m, "supported_actions", None) or []
                if "generateContent" not in actions:
                    continue

                # Skip pure TTS / audio-only live endpoints in text/image chat selector
                if any(x in model_id.lower() for x in ("-tts", "native-audio", "-live-")):
                    continue

                display_name = getattr(m, "display_name", "") or model_id
                seen_ids.add(model_id)

                badge = "MODEL"
                if is_image_model(model_id):
                    badge = "IMAGE"
                elif "gemini-4" in model_id:
                    badge = "LATEST"
                elif "pro" in model_id:
                    badge = "PRO"
                elif "flash" in model_id:
                    badge = "FLASH"

                discovered.append(
                    {
                        "id": model_id,
                        "name": display_name,
                        "badge": badge,
                    }
                )

            if discovered:
                discovered.sort(key=_model_sort_key, reverse=True)
                self._models_cache[api_key] = (now, discovered)
                return discovered
        except Exception:
            pass

        return FALLBACK_MODELS

    def validate_key(self, api_key: str) -> Dict[str, Any]:
        try:
            models = self.list_available_models(api_key, force_refresh=True)
            return {
                "valid": True,
                "model_count": len(models),
                "models": models,
                "message": f"Verified ({len(models)} live models synced).",
            }
        except Exception as e:
            self._clients.pop(api_key, None)
            return {
                "valid": False,
                "error": str(e),
            }

    def _build_contents(
        self,
        history: List[Dict[str, Any]],
        user_text: str,
        attachments: List[Dict[str, Any]],
        for_image_model: bool = False,
    ) -> List[types.Content]:
        raw_contents: List[types.Content] = []

        # For image generation models, avoid feeding long multi-turn coding history that can suppress image output
        effective_history = history[-2:] if for_image_model else history

        for msg in effective_history:
            if msg.get("role") not in ("user", "assistant"):
                continue
            role = "model" if msg["role"] == "assistant" else "user"
            parts: List[types.Part] = []

            if msg["role"] == "user":
                for att in msg.get("attachments", []):
                    att_type = att.get("type", "text")
                    if att_type in ("image", "binary") and att.get("data_base64"):
                        try:
                            raw_bytes = base64.b64decode(att["data_base64"])
                            parts.append(
                                types.Part.from_bytes(
                                    data=raw_bytes,
                                    mime_type=att.get("mime_type", "image/png"),
                                )
                            )
                        except Exception:
                            pass
                    elif att.get("content") and not for_image_model:
                        note = f"[Attached file: {att.get('filename', 'file')}]"
                        lang = att.get("language", "text")
                        parts.append(
                            types.Part.from_text(
                                text=f"{note}\n```{lang}\n{att['content']}\n```"
                            )
                        )

            msg_text = (msg.get("content") or "").strip()
            if msg_text:
                parts.append(types.Part.from_text(text=msg_text))
            elif msg["role"] == "assistant" and msg.get("attachments"):
                parts.append(types.Part.from_text(text="[Generated image]"))

            if parts:
                raw_contents.append(types.Content(role=role, parts=parts))

        current_parts: List[types.Part] = []
        for att in attachments:
            att_type = att.get("type", "text")
            if att_type in ("image", "binary") and att.get("data_base64"):
                try:
                    raw_bytes = base64.b64decode(att["data_base64"])
                    current_parts.append(
                        types.Part.from_bytes(
                            data=raw_bytes,
                            mime_type=att.get("mime_type", "image/png"),
                        )
                    )
                except Exception:
                    pass
            elif att.get("content"):
                note = f"[Attached file: {att.get('filename', 'file')}]"
                if att.get("truncated"):
                    note += " (truncated)"
                lang = att.get("language", "text")
                current_parts.append(
                    types.Part.from_text(
                        text=f"{note}\n```{lang}\n{att['content']}\n```"
                    )
                )

        prompt_text = user_text.strip() if user_text else "Please analyze the attached file(s)."
        current_parts.append(types.Part.from_text(text=prompt_text))
        raw_contents.append(types.Content(role="user", parts=current_parts))

        # Merge any consecutive Content items with the same role so Gemini API never rejects broken turn ordering
        merged: List[types.Content] = []
        for item in raw_contents:
            if merged and merged[-1].role == item.role:
                merged[-1] = types.Content(
                    role=item.role,
                    parts=list(merged[-1].parts or []) + list(item.parts or []),
                )
            else:
                merged.append(item)

        return merged

    def _extract_parts_from_response(
        self,
        chunk_or_resp: Any,
        start_time: float,
        first_token_time: Optional[float],
        full_text: str,
        generated_images: List[Dict[str, Any]],
    ) -> tuple[Optional[float], str, List[Dict[str, Any]]]:
        events: List[Dict[str, Any]] = []
        candidates = getattr(chunk_or_resp, "candidates", None) or []
        for cand in candidates:
            content_obj = getattr(cand, "content", None)
            parts = getattr(content_obj, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    if first_token_time is None:
                        first_token_time = time.time()
                    full_text += part_text
                    events.append(
                        {
                            "type": "delta",
                            "delta": part_text,
                            "ttft_ms": int((first_token_time - start_time) * 1000) if first_token_time else 0,
                        }
                    )

                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    if first_token_time is None:
                        first_token_time = time.time()
                    raw_data = inline.data
                    if isinstance(raw_data, bytes):
                        b64_str = base64.b64encode(raw_data).decode("ascii")
                    else:
                        b64_str = str(raw_data)
                    mime_type = getattr(inline, "mime_type", None) or "image/png"
                    ext = mime_type.split("/")[-1] if "/" in mime_type else "png"
                    img_item = {
                        "type": "image",
                        "generated": True,
                        "mime_type": mime_type,
                        "data_base64": b64_str,
                        "filename": f"generated_{int(time.time())}_{len(generated_images) + 1}.{ext}",
                    }
                    generated_images.append(img_item)
                    events.append(
                        {
                            "type": "image",
                            "image": img_item,
                        }
                    )
        return first_token_time, full_text, events

    def stream_chat(
        self,
        api_key: str,
        model: str,
        system_instruction: str,
        temperature: float,
        top_p: float,
        max_output_tokens: int,
        history: List[Dict[str, Any]],
        user_text: str,
        attachments: List[Dict[str, Any]],
        cancel_Check=None,
    ) -> Generator[Dict[str, Any], None, None]:
        client = self._get_client(api_key)

        # Auto-route to Nano Banana image model if user explicitly asks to generate an image while a text model is selected
        effective_model = model
        if not is_image_model(effective_model) and is_image_generation_prompt(user_text):
            effective_model = "gemini-nano-banana-2.1"

        use_image_mode = is_image_model(effective_model)
        contents = self._build_contents(history, user_text, attachments, for_image_model=use_image_mode)

        start_time = time.time()
        first_token_time: Optional[float] = None
        full_text = ""
        generated_images: List[Dict[str, Any]] = []
        usage_meta: Dict[str, Any] = {}

        try:
            if use_image_mode:
                # Image / Nano Banana models require response_modalities=["TEXT", "IMAGE"] and no coding system_instruction
                img_config = types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    temperature=temperature,
                )
                fallback_chain = [effective_model]
                for candidate_m in ("gemini-nano-banana-2.1", "gemini-2.5-flash-image", "nano-banana-pro-preview"):
                    if candidate_m not in fallback_chain:
                        fallback_chain.append(candidate_m)

                last_err = None
                resp = None
                for try_model in fallback_chain:
                    if cancel_Check and cancel_Check():
                        yield {
                            "type": "cancelled",
                            "full_text": full_text,
                            "generated_images": generated_images,
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                        return
                    try:
                        resp = client.models.generate_content(
                            model=try_model,
                            contents=contents,
                            config=img_config,
                        )
                        effective_model = try_model
                        break
                    except Exception as err:
                        last_err = err
                        continue

                if resp is None:
                    raise last_err or RuntimeError("Image generation failed.")

                first_token_time, full_text, events = self._extract_parts_from_response(
                    resp, start_time, first_token_time, full_text, generated_images
                )
                for ev in events:
                    yield ev

                if getattr(resp, "usage_metadata", None):
                    um = resp.usage_metadata
                    usage_meta = {
                        "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
                        "completion_tokens": getattr(um, "candidates_token_count", 0) or 0,
                        "total_tokens": getattr(um, "total_token_count", 0) or 0,
                    }
            else:
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction if system_instruction else None,
                    temperature=temperature,
                    top_p=top_p,
                    max_output_tokens=max_output_tokens,
                )
                response_stream = client.models.generate_content_stream(
                    model=effective_model,
                    contents=contents,
                    config=config,
                )
                for chunk in response_stream:
                    if cancel_Check and cancel_Check():
                        yield {
                            "type": "cancelled",
                            "full_text": full_text,
                            "generated_images": generated_images,
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        }
                        return

                    first_token_time, full_text, events = self._extract_parts_from_response(
                        chunk, start_time, first_token_time, full_text, generated_images
                    )
                    for ev in events:
                        yield ev

                    if getattr(chunk, "usage_metadata", None):
                        um = chunk.usage_metadata
                        usage_meta = {
                            "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
                            "completion_tokens": getattr(um, "candidates_token_count", 0) or 0,
                            "total_tokens": getattr(um, "total_token_count", 0) or 0,
                        }

            elapsed_ms = int((time.time() - start_time) * 1000)
            yield {
                "type": "done",
                "full_text": full_text,
                "generated_images": generated_images,
                "elapsed_ms": elapsed_ms,
                "ttft_ms": int((first_token_time - start_time) * 1000) if first_token_time else elapsed_ms,
                "usage": usage_meta,
                "model": effective_model,
            }
        except Exception as e:
            yield {
                "type": "error",
                "error": str(e),
                "full_text": full_text,
                "elapsed_ms": int((time.time() - start_time) * 1000),
            }
