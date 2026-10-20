"""Isolated UI acceptance fixture. All model/audio responses are synthetic.

Run with MVP_DATA_DIR inside artifacts/. No real API key or live account is read.
"""
import asyncio
import io
import json
import math
import struct
import wave

import mvp_preview_server as preview
from app import genui_ai, speech
from app.genui_prompt import encode_authored_ui

preview.app.state.settings.ai_api_key = "synthetic-browser-fixture"
preview.app.state.settings.ai_grounding = False

async def response(settings, sources, messages, profile, tier):
    text = "我整理了下面的示例课程，输入课程名可以筛选，选择后可以继续提问。"
    for i in range(0, len(text), 5):
        yield {"type":"preview","text":text[i:i+5]}
        await asyncio.sleep(.16)
    ui = {"state":{"query":"","rows":[
        {"id":"a","title":"示例 · 设计导论","time":"周二 10:00"},
        {"id":"b","title":"示例 · 数据分析","time":"周四 14:00"}]},
        "nodes":[{"id":"schedule","type":"Section","props":{"title":"本周课程","surface":"plain"},"children":[
            {"id":"query","type":"TextInput","props":{"label":"筛选课程","bind":"query"}},
            {"id":"courses","type":"Collection","props":{"items":{"$expr":"search(rows,query)"},"keyField":"id"},"children":[
                {"id":"title","type":"Prose","props":{"text":{"$bind":"item.title"}}},
                {"id":"time","type":"Prose","props":{"text":{"$bind":"item.time"},"variant":"caption"}},
                {"id":"ask","type":"Button","props":{"label":"安排准备时间"},"on":{"click":{"kind":"ask_model","prompt":"帮我安排这门课的准备时间","values":{"course":{"$bind":"item.title"}}}}}
            ]}
        ]}, {"id":"upload","type":"Button","props":{"label":"添加课程材料"},"on":{"click":{"kind":"host","name":"upload_material","params":{}}}}]}
    answer = text + encode_authored_ui(ui)
    yield {"type":"delta","text":answer}
    yield {"type":"complete","result":{"answer":answer,"citations":[],"image_sources":[],"claims":[]},"usage":{}}

def audio(*args):
    target=io.BytesIO()
    with wave.open(target,"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
        wav.writeframes(b"".join(struct.pack("<h",int(700*math.sin(i*2*math.pi*220/16000))) for i in range(64000)))
    return target.getvalue()

genui_ai.stream_reply=response
speech.synthesize=audio

if __name__ == "__main__":
    import uvicorn
    preview.seed()
    uvicorn.run(preview.app,host="127.0.0.1",port=preview.PORT,log_level="warning")
