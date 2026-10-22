"""Small, playable synthetic media; no user data or external codecs."""
import io
import math
import struct
import wave

def png(index=0):
    from PIL import Image
    output=io.BytesIO()
    Image.new('RGB',(96,64),(index*31%255,100,160)).save(output,format='PNG')
    return output.getvalue()

def wav(seconds=2):
    output=io.BytesIO()
    with wave.open(output,'wb') as file:
        file.setnchannels(1);file.setsampwidth(2);file.setframerate(16000)
        file.writeframes(b''.join(struct.pack('<h',int(5000*math.sin(i*2*math.pi*440/16000))) for i in range(int(seconds*16000))))
    return output.getvalue()

def mp4():
    import av
    from PIL import Image
    output=io.BytesIO()
    with av.open(output,'w',format='mp4') as container:
        stream=container.add_stream('libx264',rate=2)
        stream.width=96;stream.height=64;stream.pix_fmt='yuv420p'
        for index in range(4):
            frame=av.VideoFrame.from_image(Image.new('RGB',(96,64),(index*60,100,100)))
            for packet in stream.encode(frame):container.mux(packet)
        for packet in stream.encode():container.mux(packet)
    return output.getvalue()

if __name__=='__main__':
    from pathlib import Path
    folder=Path('artifacts/composer-fixtures');folder.mkdir(parents=True,exist_ok=True)
    for index in range(6):(folder/f'image-{index}.png').write_bytes(png(index))
    (folder/'tone.wav').write_bytes(wav(20));(folder/'clip.mp4').write_bytes(mp4())
