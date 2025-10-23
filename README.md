# Python Pygame 3x3 Layered Grid Demo

This is a small Pygame demo showing a window split into two parts:

- Top: a 3x3 grid of cells. Each cell contains 3 layers of images (simulated with colored rectangles).
- Bottom: a display area that shows the currently selected cell's active layer.

Controls:

- Click a cell in the top grid to select it. Left click cycles the layer forward; right click cycles backward.
- Press Esc or close the window to quit.

Run:

1. Create a virtual environment (optional):

   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

2. Install dependencies:

   pip install -r requirements.txt

3. Run the game:

   python main.py

Notes:

- The demo uses generated colored surfaces instead of image files to keep the example self-contained.
- You can replace the generated surfaces with real images by loading with `pygame.image.load`.
