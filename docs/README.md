# Demo assets

Media used by the README and the ComfyUI node page. Keep them small: they are
committed to the repository.

| File | What it shows |
|---|---|
| `subtitle-residue.gif` | top: a clean take passes; bottom: the same shot with burned-in subtitles fails |
| `frozen-detection.gif` | top: a moving take passes; bottom: a take frozen for 0.83 s fails |
| `blank-detection.gif` | top: a normal take passes; bottom: a take with black frames fails |
| `screenshot-subtitle.png` | the HTML report for the subtitle failure — every check's measured values plus a red-rimmed contact sheet |
| `demo-subtitle.html` | the report above, as a live file you can open |
| `demo-good.html` | the same report for a passing take |

Rebuild the GIFs (needs ffmpeg; the fixtures ship with the repo):

```bash
# subtitle: clean vs residue, bottom band cropped
ffmpeg -y -i testmedia/synthetic/good.mp4 -i testmedia/synthetic/subtitle.mp4 \
  -filter_complex "[0:v]crop=640:130:0:210,scale=480:-1,drawbox=x=0:y=0:w=iw:h=ih:color=0x22aa55@0.95:t=3,drawtext=text='clean  PASS':fontsize=18:fontcolor=0x22aa55:x=6:y=4[a];\
[1:v]crop=640:130:0:210,scale=480:-1,drawbox=x=0:y=0:w=iw:h=ih:color=0xdd2222@0.95:t=3,drawtext=text='residue  FAIL':fontsize=18:fontcolor=0xdd2222:x=6:y=4[b];\
[a][b]vstack=inputs=2,fps=12,split[x][y];[x]palettegen=max_colors=64[p];[y][p]paletteuse=dither=bayer" \
  -loop 0 docs/subtitle-residue.gif
```

On Windows, `drawtext` needs an explicit `fontfile=` or ffmpeg aborts with a
Fontconfig error.

Rebuild the reports:

```bash
takecheck check testmedia/synthetic/subtitle.mp4 --spec comfyui/takes.yml \
  --html docs/demo-subtitle.html --quiet
takecheck check testmedia/synthetic/good.mp4 --spec comfyui/takes.yml \
  --html docs/demo-good.html --quiet
```

The screenshot is a headless Chrome capture of `demo-subtitle.html`:

```bash
chrome --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
  --window-size=1100,1300 --virtual-time-budget=5000 \
  --screenshot=docs/screenshot-subtitle.png docs/demo-subtitle.html
```
