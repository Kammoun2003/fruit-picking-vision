# Running LabelImg 1.8.6 on Python 3.10+

LabelImg 1.8.6 (the last release on PyPI) crashes on Python 3.10 and newer as soon as you scroll, zoom or draw:

```
TypeError: setValue(self, a0: int): argument 1 has unexpected type 'float'
```

Since Python 3.10, PyQt5 no longer converts a `float` to an `int` silently, and LabelImg passes floats to several Qt methods that expect integers.

## What did not work

- **Python 3.9 / 3.7 instead of 3.10:** on my machine these installs were broken or too old. pip could not find a prebuilt `PyQt5-sip` wheel for Python 3.7, so it tried to compile it and asked for Microsoft C++ Build Tools.

## The fix: wrap the values in `int(...)`

Install LabelImg in its own virtual environment, then patch 8 lines in the installed package (`<venv>\Lib\site-packages\`).

**`labelImg/labelImg.py`**
```python
bar.setValue(int(bar.value() + bar.singleStep() * units))   # scroll_request
self.zoom_widget.setValue(int(value))                        # set_zoom
h_bar.setValue(int(new_h_bar_value))                         # zoom_request
v_bar.setValue(int(new_v_bar_value))                         # zoom_request
```

**`libs/canvas.py`** (paintEvent)
```python
p.drawRect(int(left_top.x()), int(left_top.y()), int(rect_width), int(rect_height))
p.drawLine(int(self.prev_point.x()), 0, int(self.prev_point.x()), int(self.pixmap.height()))
p.drawLine(0, int(self.prev_point.y()), int(self.pixmap.width()), int(self.prev_point.y()))
```

**`libs/shape.py`** (paint, shown when "display labels" is on)
```python
painter.drawText(int(min_x), int(min_y), self.label)
```

## Install steps (Windows, CMD)

```bat
py -3.10 -m venv D:\venvs\labelimg
D:\venvs\labelimg\Scripts\activate
python -m pip install labelImg
```

Apply the 8 changes above (keep a copy of each original file), then start it with an image folder and a class file:

```bat
labelImg D:\path\to\images D:\path\to\classes.txt
```

Test zooming, scrolling and drawing a box before labeling for real.

LabelImg is MIT-licensed; these changes only touch the installed copy and are shared here as notes.
