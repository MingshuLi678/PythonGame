import sys
import random
import time
import pygame
from math import floor


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 800

FPS = 30

# UI layout ratios
GRID_RATIO = 0.65  # top area fraction

WILDCARD_COLOR = (255, 255, 255)


def generate_colors(n):
    # kept for backward-compat but not used in symbol-based mode
    return []


SHAPES = ['circle', 'triangle', 'square', 'diamond', 'pentagon', 'hexagon', 'cross', 'plus', 'oval', 'trapezoid']
# extra shapes that will be introduced at higher levels
EXTRA_SHAPES = ['four_star', 'five_star', 'hollow_circle']


def generate_shapes(n, pool=None):
    """Generate a list of n shape names cycling through `pool` (defaults to SHAPES + EXTRA_SHAPES).

    `pool` can be a subset to control which shapes are available at a given level.
    """
    if pool is None:
        pool = SHAPES + EXTRA_SHAPES
    syms = []
    i = 0
    while len(syms) < n:
        syms.append(pool[i % len(pool)])
        i += 1
    return syms


class Game:
    def __init__(self, screen):
        pygame.font.init()
        self.screen = screen
        self.clock = pygame.time.Clock()
        # Prefer common English UI fonts; reduce sizes slightly so popup text fits
        preferred_fonts = ["Segoe UI", "Arial", "Tahoma", None]
        chosen_small = None
        chosen_big = None
        for fname in preferred_fonts:
            try:
                f = pygame.font.SysFont(fname, 20)
                b = pygame.font.SysFont(fname, 28)
                # test whether font can render a common ASCII character
                if f.render("A", True, (0, 0, 0)):
                    chosen_small = f
                    chosen_big = b
                    break
            except Exception:
                continue
        if chosen_small is None:
            self.font = pygame.font.SysFont(None, 20)
            self.big_font = pygame.font.SysFont(None, 28)
        else:
            self.font = chosen_small
            self.big_font = chosen_big

        self.level = 1
        # game state: 'menu', 'playing', 'gameover'
        self.state = 'menu'
        self.start_level(self.level)

        # undo stack: list of snapshots (board, preview, score, level_start_ts)
        import copy
        self._copy = copy
        self.undo_stack = []

        self.running = True
        # initialize audio (mixer) safely
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1)
            self.audio_ok = True
        except Exception:
            self.audio_ok = False

        # prepare simple procedural sounds if audio is available
        if self.audio_ok:
            # helper to generate a short sine wave Sound
            def make_tone(freq, duration=0.08, volume=0.5):
                import math, array
                sample_rate = 22050
                n_samples = int(sample_rate * duration)
                buf = array.array('h')
                max_amp = 32767 * volume
                for i in range(n_samples):
                    t = i / sample_rate
                    v = int(max_amp * math.sin(2 * math.pi * freq * t))
                    buf.append(v)
                return pygame.mixer.Sound(buffer=buf)

            # click: higher short tone; eliminate: lower longer tone
            try:
                self.snd_click = make_tone(1200, 0.05, 0.4)
                self.snd_elim = make_tone(600, 0.14, 0.6)
            except Exception:
                self.snd_click = None
                self.snd_elim = None
            # create a short victory jingle (sequence of rising notes)
            try:
                import math, array
                sample_rate = 22050
                freqs = [880, 1100, 1320]
                buf = array.array('h')
                for freq in freqs:
                    duration = 0.18
                    n_samples = int(sample_rate * duration)
                    for i in range(n_samples):
                        t = i / sample_rate
                        # simple decay envelope to avoid clicks
                        env = 1.0 - (i / n_samples)
                        v = int(32767 * 0.45 * env * math.sin(2 * math.pi * freq * t))
                        buf.append(v)
                self.snd_victory = pygame.mixer.Sound(buffer=buf)
            except Exception:
                self.snd_victory = None
        else:
            self.snd_click = None
            self.snd_elim = None
            self.snd_victory = None

        # load persistent best-level (history)
        self.history_file = "game_history.json"
        self.best_level = 0
        try:
            import json, os
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.best_level = int(data.get('best_level', 0))
        except Exception:
            self.best_level = 0

    def start_level(self, level):
        # compute dimensions based on level with max depth 3
        # progression: start w=3,h=3,d=1; increase d up to 3, then alternate increasing h and w
        self.level = level
        # compute dims
        base_w = 3
        base_h = 3
        d = 1
        w = base_w
        h = base_h
        lvl = 1
        # iterate levels to compute dims for requested level
        while lvl < level:
            if d < 3:
                d += 1
            else:
                # alternate increasing h then w
                if (h - base_h) <= (w - base_w):
                    h += 1
                else:
                    w += 1
            lvl += 1

        self.w = w
        self.h = h
        self.d = d
        self.total_blocks = w * h * d

        # generate blocks: make triplet_count and remainder
        triplet_count = self.total_blocks // 3
        remainder = self.total_blocks % 3

        # control which shapes are available depending on level so we can introduce
        # new shapes gradually (avoid making the game too hard immediately).
        # Base pool is SHAPES; extras are added at specific levels.
        pool = list(SHAPES)  # copy
        if level >= 5:
            pool.append('four_star')
        if level >= 6:
            pool.append('five_star')
        if level >= 7:
            pool.append('hollow_circle')

        top_slots = w * h
        distinct_symbols = max(1, min(triplet_count, top_slots))
        symbols = generate_shapes(distinct_symbols, pool=pool)

        # build flat list of symbols (triplets).
        # To keep playability when introducing new shapes, make newly-introduced
        # shapes rare initially: give each new shape a single triplet, then
        # distribute remaining triplets among the older/base symbols.
        flat = []
        extra_set = set(EXTRA_SHAPES)
        # identify which of the chosen symbols are extras (newly introduced)
        new_symbols = [s for s in symbols if s in extra_set]
        base_symbols = [s for s in symbols if s not in extra_set]

        remaining_triplets = triplet_count
        # assign one triplet for each new symbol (so they appear but are rare)
        for sym in new_symbols:
            flat.extend([sym, sym, sym])
            remaining_triplets -= 1

        # distribute remaining triplets among base symbols if available, else among new symbols
        if base_symbols and remaining_triplets > 0:
            for i in range(remaining_triplets):
                sym = base_symbols[i % len(base_symbols)]
                flat.extend([sym, sym, sym])
        elif remaining_triplets > 0 and new_symbols:
            for i in range(remaining_triplets):
                sym = new_symbols[i % len(new_symbols)]
                flat.extend([sym, sym, sym])

        # append extra symbols for remainder (no wildcards)
        offset = triplet_count
        for j in range(remainder):
            if flat:
                # pick a symbol cyclically from the symbols list
                sym = symbols[(offset + j) % len(symbols)]
                flat.append(sym)
            else:
                flat.append(symbols[0])

        # ensure total length equals total_blocks by adding the first symbol if needed
        while len(flat) < self.total_blocks:
            flat.append(symbols[0])
        while len(flat) > self.total_blocks:
            flat.pop()

        random.shuffle(flat)

        # prepare empty stacks as lists of length d filled with None
        positions = [(x, y) for x in range(w) for y in range(h)]
        random.shuffle(positions)
        stacks = {pos: [None] * d for pos in positions}

        # Randomly distribute all blocks (including wildcards) onto the board.
        # First assign the top layer for every position from the shuffled flat list so white tiles
        # can appear in the upper grid like other shapes.
        for pos in positions:
            if flat:
                stacks[pos][-1] = flat.pop()
            else:
                stacks[pos][-1] = '*'

        # Fill remaining lower slots (bottom-up) from the remaining flat list
        for pos in positions:
            stack = stacks[pos]
            # fill indices 0 .. d-2 (if any)
            for zi in range(d - 1):
                if flat:
                    stack[zi] = flat.pop()
                else:
                    stack[zi] = '*'

        # convert stacks to board with bottom->top lists
        self.board = {}
        for pos in positions:
            self.board[pos] = stacks[pos]

        # preview area (list of symbols)
        self.preview = []

        # reset undo stack for the level
        self.undo_stack = []

        # timer
        self.level_time = 100  # seconds
        self.level_start_ts = time.time()

        # score
        self.score = 0

        # feature hint popups: show only the first time each feature appears
        if self.level == 2:
            self.hint_shown = True
            self.hint_start = time.time()
            self.hint_msg = "Undo unlocked: press U or click Undo to revert one step."
        elif self.level == 3:
            self.hint_shown = True
            self.hint_start = time.time()
            self.hint_msg = "Shuffle unlocked: press R or click Shuffle to reshuffle remaining blocks."
        else:
            self.hint_shown = False
            self.hint_start = None
            self.hint_msg = ""

        # update best-level if higher
        try:
            if level > self.best_level:
                self.best_level = level
                import json
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump({'best_level': self.best_level}, f)
        except Exception:
            pass

    def get_top(self, x, y):
        stack = self.board.get((x, y), [])
        return stack[-1] if stack else None

    def pop_top(self, x, y):
        stack = self.board.get((x, y), [])
        if stack:
            return stack.pop()
        return None

    def shuffle_remaining(self):
        """Randomize the positions of all remaining blocks (all items still in self.board stacks).

        This preserves the counts and depths but redistributes items across positions.
        """
        # collect all remaining items and record each position's current height
        items = []
        positions = list(self.board.keys())
        heights = {}
        for pos in positions:
            stack = self.board.get(pos, [])
            heights[pos] = len(stack)
            items.extend(stack)

        # Shuffle items, then refill each position with the same height it had before
        random.shuffle(items)
        new_board = {}
        # Use positions in random order to avoid introducing positional bias
        random.shuffle(positions)
        for pos in positions:
            h = heights.get(pos, 0)
            new_stack = []
            for _ in range(h):
                # pop from items (already shuffled)
                if items:
                    new_stack.append(items.pop())
                else:
                    # safety: no items left (shouldn't happen), leave stack empty
                    break
            new_board[pos] = new_stack

        # Replace board while preserving any positions not in heights (unlikely)
        for pos in new_board:
            self.board[pos] = new_board[pos]

    def all_cleared(self):
        return all(len(s) == 0 for s in self.board.values())

    def try_eliminate_preview(self):
        """Only eliminate if the last three items in preview form a valid triple (wildcard '*' allowed).

        Returns True if any elimination happened (including cascades).
        """
        eliminated_any = False
        # keep checking tail while possible
        while len(self.preview) >= 3:
            tail = self.preview[-3:]
            # if all wildcards, remove
            if all(t == '*' for t in tail):
                for _ in range(3):
                    self.preview.pop()
                self.score += 10
                eliminated_any = True
                # play elimination sound
                try:
                    if getattr(self, 'snd_elim', None):
                        self.snd_elim.play()
                except Exception:
                    pass
                continue

            # find a non-wild symbol in the tail (if any)
            non_wild = next((t for t in tail if t != '*'), None)
            if non_wild is None:
                break
            # check whether each element is either the same symbol or wildcard
            if all((t == non_wild or t == '*') for t in tail):
                for _ in range(3):
                    self.preview.pop()
                self.score += 10
                eliminated_any = True
                # play elimination sound
                try:
                    if getattr(self, 'snd_elim', None):
                        self.snd_elim.play()
                except Exception:
                    pass
                continue

            # otherwise cannot eliminate the tail
            break

        return eliminated_any

    def handle_click(self, pos):
        mx, my = pos
        grid_h = int(WINDOW_HEIGHT * GRID_RATIO)
        if my > grid_h:
            # click in preview or UI area -> ignore for now
            return
        # map mx,my to grid x,y
        grid_w = WINDOW_WIDTH
        cell_w = grid_w // self.w
        cell_h = grid_h // self.h
        x = min(self.w - 1, mx // cell_w)
        y = min(self.h - 1, my // cell_h)
        # only top is clickable
        top = self.get_top(x, y)
        if top is not None and self.state == 'playing':
            # push snapshot for undo
            snap = (self._copy.deepcopy(self.board), list(self.preview), int(self.score), float(self.level_start_ts))
            self.undo_stack.append(snap)
            block = self.pop_top(x, y)
            # play click sound
            try:
                if getattr(self, 'snd_click', None):
                    self.snd_click.play()
            except Exception:
                pass
            self.preview.append(block)
            # after adding, try eliminate
            self.try_eliminate_preview()

            # check for all cleared but preview not empty -> game over
            if self.all_cleared() and len(self.preview) > 0:
                self.state = 'gameover'
            # if everything cleared including preview -> victory for this level
            if self.all_cleared() and len(self.preview) == 0:
                # set victory overlay for ~3 seconds then advance
                self.victory_until = time.time() + 3.0
                # play victory sound
                try:
                    if getattr(self, 'snd_victory', None):
                        self.snd_victory.play()
                except Exception:
                    pass

    def update(self):
        # check timer
        elapsed = time.time() - self.level_start_ts
        self.remaining = max(0, self.level_time - int(elapsed))
        if getattr(self, 'timesup_until', None):
            # if times-up overlay active, wait for it to expire and then restart level
            if time.time() >= self.timesup_until:
                self.timesup_until = None
                # restart same level
                self.start_level(self.level)
            return

        if self.remaining <= 0:
            # level failed: show a "Time's up!" overlay for a short moment then restart
            if not getattr(self, 'timesup_until', None):
                self.timesup_until = time.time() + 3.0
            return
        # if in victory overlay, wait until it's done
        if getattr(self, 'victory_until', None):
            if time.time() >= self.victory_until:
                self.victory_until = None
                self.start_level(self.level + 1)
            return

        # check win (catch cases where elimination finished game outside handle_click)
        if self.all_cleared() and len(self.preview) == 0:
            # set victory overlay and play sound
            self.victory_until = time.time() + 3.0
            try:
                if getattr(self, 'snd_victory', None):
                    self.snd_victory.play()
            except Exception:
                pass

    def draw(self):
        self.screen.fill((200, 200, 200))
        # if in menu state, draw start screen
        if self.state == 'menu':
            # comic-style black-and-white background with halftone dots
            self.screen.fill((245, 245, 245))
            # draw halftone-like dots pattern (sparse) for comic texture
            dot_color = (200, 200, 200)
            step = 10
            for y in range(0, WINDOW_HEIGHT, step):
                for x in range((y // step) % 2 * (step // 2), WINDOW_WIDTH, step):
                    if (x + y) % (step * 2) == 0:
                        pygame.draw.circle(self.screen, dot_color, (x + 3, y + 3), 2)

            # bold frame
            pygame.draw.rect(self.screen, (0, 0, 0), (20, 20, WINDOW_WIDTH - 40, WINDOW_HEIGHT - 40), 6)

            # comic burst title (black & white jagged burst + halftone + outlined text)
            def draw_comic_burst(surface, text, top_y, w=720, h=180):
                import math
                surf = pygame.Surface((w, h), pygame.SRCALPHA)
                cx = w // 2
                cy = h // 2

                # jagged burst polygon
                pts = []
                spikes = 16
                for i in range(spikes * 2):
                    angle = (i / (spikes * 2.0)) * 2 * math.pi
                    r = (min(w, h) * 0.45) * (1.0 if i % 2 == 0 else 0.55)
                    x = cx + int(r * math.cos(angle))
                    y = cy + int(r * math.sin(angle))
                    pts.append((x, y))

                # white fill with thick black outline
                pygame.draw.polygon(surf, (255, 255, 255), pts)
                pygame.draw.polygon(surf, (0, 0, 0), pts, 6)

                # halftone-style dots (light gray) inside the burst
                dot_col = (200, 200, 200)
                spacing = 12
                maxr = min(w, h) * 0.45
                for dx in range(0, w, spacing):
                    for dy in range(0, h, spacing):
                        px = dx + spacing // 2
                        py = dy + spacing // 2
                        dist = math.hypot(px - cx, py - cy)
                        if dist < maxr:
                            radius = int(max(0, (1.0 - dist / maxr) ) * 3)
                            if radius > 0:
                                pygame.draw.circle(surf, dot_col, (px, py), radius)

                # render big outlined title
                try:
                    title_font = pygame.font.SysFont(None, 72)
                except Exception:
                    title_font = self.big_font
                txt = title_font.render(text, True, (255, 255, 255))
                # outline by rendering black copies around
                outline_color = (0, 0, 0)
                for ox in (-3, -2, -1, 0, 1, 2, 3):
                    for oy in (-3, -2, -1, 0, 1, 2, 3):
                        if abs(ox) + abs(oy) == 0:
                            continue
                        surf.blit(title_font.render(text, True, outline_color), (cx - txt.get_width() // 2 + ox, cy - txt.get_height() // 2 + oy - 6))
                surf.blit(txt, (cx - txt.get_width() // 2, cy - txt.get_height() // 2 - 6))

                # small subtitle 'GAME' below
                try:
                    sub_font = pygame.font.SysFont(None, 28)
                except Exception:
                    sub_font = self.font
                sub_s = sub_font.render('GAME', True, (0, 0, 0))
                surf.blit(sub_s, (cx - sub_s.get_width() // 2, cy + txt.get_height() // 2 - 0))

                surface.blit(surf, ((WINDOW_WIDTH - w) // 2, top_y))

            draw_comic_burst(self.screen, 'MATCH-3', 40, w=720, h=180)

            # draw start button (centered)
            start_txt = self.big_font.render("Start", True, (255, 255, 255))
            best_txt = self.big_font.render("Best", True, (255, 255, 255))
            btn_rect = pygame.Rect((WINDOW_WIDTH - 200) // 2, 220, 200, 60)
            pygame.draw.rect(self.screen, (0, 0, 0), btn_rect, 4)  # black border
            pygame.draw.rect(self.screen, (30, 30, 30), btn_rect.inflate(-6, -6))
            self.screen.blit(start_txt, (btn_rect.left + (btn_rect.width - start_txt.get_width()) // 2, btn_rect.top + 12))

            # Best button below start (green fill with black border)
            best_btn = pygame.Rect(btn_rect.left, btn_rect.bottom + 12, btn_rect.width, btn_rect.height)
            pygame.draw.rect(self.screen, (0, 0, 0), best_btn, 4)
            pygame.draw.rect(self.screen, (60, 140, 60), best_btn.inflate(-6, -6))
            self.screen.blit(best_txt, (best_btn.left + (best_btn.width - best_txt.get_width()) // 2, best_btn.top + (best_btn.height - best_txt.get_height()) // 2))

            # rules preview (below best button)
            rules_preview = [
                "Click three identical shapes to remove them (match-3).",
                "Clear all shapes to win the level.",
                "More shapes will appear in later levels.",
                "Level 2 adds a 2-layer stack; Level 3 adds a 3-layer stack.",
                "Try to clear all blocks within the time limit! (*^▽^*)",
            ]
            for i, line in enumerate(rules_preview):
                txt = self.font.render(line, True, (10, 10, 10))
                self.screen.blit(txt, ((WINDOW_WIDTH - txt.get_width()) // 2, best_btn.bottom + 12 + i * 20))

            # draw best-level popup if requested
            if getattr(self, 'showing_best_until', None) and time.time() < self.showing_best_until:
                popup = pygame.Rect((WINDOW_WIDTH - 320) // 2, best_btn.bottom + 12 + len(rules_preview) * 20 + 12, 320, 48)
                pygame.draw.rect(self.screen, (255, 255, 220), popup)
                pygame.draw.rect(self.screen, (0, 0, 0), popup, 3)
                best_msg = f"Highest level reached: {self.best_level}"
                bt = self.font.render(best_msg, True, (0, 0, 0))
                self.screen.blit(bt, (popup.left + (popup.width - bt.get_width()) // 2, popup.top + (popup.height - bt.get_height()) // 2))
            pygame.display.flip()
            return

        if self.state == 'gameover':
            over = self.big_font.render("Game Over", True, (200, 20, 20))
            retry = self.big_font.render("Back to Menu", True, (255, 255, 255))
            self.screen.blit(over, ((WINDOW_WIDTH - over.get_width()) // 2, 120))
            btn_rect = pygame.Rect((WINDOW_WIDTH - 300) // 2, 220, 300, 60)
            pygame.draw.rect(self.screen, (200, 20, 20), btn_rect)
            self.screen.blit(retry, (btn_rect.left + (btn_rect.width - retry.get_width()) // 2, btn_rect.top + 12))
            pygame.display.flip()
            return
        grid_h = int(WINDOW_HEIGHT * GRID_RATIO)
        grid_w = WINDOW_WIDTH
        cell_w = grid_w // self.w
        cell_h = grid_h // self.h

        def draw_block(surface, rect, item, sym_font=None):
            # item is a symbol string, '*' for wildcard
            if sym_font is None:
                sym_font = self.big_font
            if item == '*':
                bg = (255, 255, 255)  # white wildcard
                fg = (0, 0, 0)
            else:
                bg = (0, 0, 0)  # black background
                fg = (255, 255, 255)
            pygame.draw.rect(surface, bg, rect)
            pygame.draw.rect(surface, (40, 40, 40), rect, 2)
            txt = sym_font.render(str(item), True, fg)
            tx = rect.left + (rect.width - txt.get_width()) // 2
            ty = rect.top + (rect.height - txt.get_height()) // 2
            surface.blit(txt, (tx, ty))

        # shape drawing helpers
        def regular_polygon(center, radius, sides):
            import math

            cx, cy = center
            pts = []
            for i in range(sides):
                angle = (2 * math.pi * i / sides) - math.pi / 2
                x = cx + radius * math.cos(angle)
                y = cy + radius * math.sin(angle)
                pts.append((x, y))
            return pts

        def draw_shape(surface, rect, shape, color):
            cx = rect.left + rect.width / 2
            cy = rect.top + rect.height / 2
            r = min(rect.width, rect.height) * 0.35
            if shape == 'circle':
                pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r))
            elif shape == 'square':
                s = int(r * 1.4)
                rr = pygame.Rect(int(cx - s / 2), int(cy - s / 2), s, s)
                pygame.draw.rect(surface, color, rr)
            elif shape == 'triangle':
                pts = regular_polygon((cx, cy + r * 0.15), r * 1.05, 3)
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'diamond':
                pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'pentagon':
                pts = regular_polygon((cx, cy), r * 1.1, 5)
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'hexagon':
                pts = regular_polygon((cx, cy), r * 1.0, 6)
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'cross':
                w = int(r * 0.6)
                h = int(r * 2.0)
                pygame.draw.rect(surface, color, (int(cx - w / 2), int(cy - h / 2), w, h))
                pygame.draw.rect(surface, color, (int(cx - h / 2), int(cy - w / 2), h, w))
            elif shape == 'plus':
                w = int(r * 0.5)
                h = int(r * 1.6)
                pygame.draw.rect(surface, color, (int(cx - w / 2), int(cy - h / 2), w, h))
                pygame.draw.rect(surface, color, (int(cx - h / 2), int(cy - w / 2), h, w))
            elif shape == 'oval':
                rr = pygame.Rect(int(cx - r * 1.2), int(cy - r * 0.9), int(r * 2.4), int(r * 1.8))
                pygame.draw.ellipse(surface, color, rr)
            elif shape == 'trapezoid':
                pts = [(cx - r, cy + r), (cx + r, cy + r), (cx + r * 0.6, cy - r), (cx - r * 0.6, cy - r)]
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'four_star':
                # draw a simple 4-point star (like a burst)
                pts = [
                    (cx, cy - r * 1.1),
                    (cx + r * 0.25, cy - r * 0.25),
                    (cx + r * 1.1, cy),
                    (cx + r * 0.25, cy + r * 0.25),
                    (cx, cy + r * 1.1),
                    (cx - r * 0.25, cy + r * 0.25),
                    (cx - r * 1.1, cy),
                    (cx - r * 0.25, cy - r * 0.25),
                ]
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'five_star':
                # 5-point star using a simple algorithm
                import math
                pts = []
                outer = r * 1.05
                inner = r * 0.45
                for i in range(10):
                    ang = math.pi / 2 + i * (2 * math.pi / 10)
                    rad = outer if i % 2 == 0 else inner
                    x = cx + rad * math.cos(ang)
                    y = cy - rad * math.sin(ang)
                    pts.append((x, y))
                pygame.draw.polygon(surface, color, pts)
            elif shape == 'hollow_circle':
                # draw an outer circle then an inner hole to make it hollow
                pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r))
                pygame.draw.circle(surface, (0, 0, 0), (int(cx), int(cy)), int(r * 0.55))
            else:
                # fallback: circle
                pygame.draw.circle(surface, color, (int(cx), int(cy)), int(r))

        # draw grid (top-down: show top shape and count)
        for x in range(self.w):
            for y in range(self.h):
                rx = x * cell_w
                ry = y * cell_h
                rect = pygame.Rect(rx + 2, ry + 2, cell_w - 4, cell_h - 4)
                stack = self.board.get((x, y), [])
                if stack:
                    top = stack[-1]
                    # top is a shape string or '*'
                    # draw background and shape
                    if top == '*':
                        # wildcard: white tile, no symbol
                        pygame.draw.rect(self.screen, (255, 255, 255), rect)
                        pygame.draw.rect(self.screen, (40, 40, 40), rect, 2)
                    else:
                        pygame.draw.rect(self.screen, (0, 0, 0), rect)
                        pygame.draw.rect(self.screen, (40, 40, 40), rect, 2)
                        draw_shape(self.screen, rect, top, (255, 255, 255))
                    # small text for stack size
                    txt = self.font.render(str(len(stack)), True, (255, 255, 255) if top != '*' else (0, 0, 0))
                    self.screen.blit(txt, (rx + 6, ry + 6))
                else:
                    pygame.draw.rect(self.screen, (120, 120, 120), rect)
                pygame.draw.rect(self.screen, (50, 50, 50), rect, 2)

        # draw divider
        pygame.draw.line(self.screen, (50, 50, 50), (0, grid_h), (WINDOW_WIDTH, grid_h), 4)

        # draw preview area
        preview_top = grid_h + 10
        preview_rect = pygame.Rect(10, preview_top, WINDOW_WIDTH - 20, WINDOW_HEIGHT - preview_top - 10)
        pygame.draw.rect(self.screen, (240, 240, 240), preview_rect)
        pygame.draw.rect(self.screen, (80, 80, 80), preview_rect, 2)

        # draw preview items horizontally
        px = preview_rect.left + 10
        py = preview_rect.top + 10
        pw = 48
        ph = 48
        gap = 8
        for i, item in enumerate(self.preview):
            r = pygame.Rect(px + i * (pw + gap), py, pw, ph)
            if item == '*':
                pygame.draw.rect(self.screen, (255, 255, 255), r)
                pygame.draw.rect(self.screen, (40, 40, 40), r, 2)
            else:
                pygame.draw.rect(self.screen, (0, 0, 0), r)
                pygame.draw.rect(self.screen, (40, 40, 40), r, 2)
                draw_shape(self.screen, r, item, (255, 255, 255))

        # draw UI: timer, level, score, rules
        ui_x = preview_rect.left + 10
        ui_y = py + ph + 12
        # make timer red when under 10 seconds to increase urgency
        timer_color = (200, 20, 20) if getattr(self, 'remaining', 0) < 10 else (10, 10, 10)
        timer_txt = self.big_font.render(f"Time: {self.remaining}s", True, timer_color)
        level_txt = self.big_font.render(f"Level: {self.level} ({self.w}x{self.h}x{self.d})", True, (10, 10, 10))
        score_txt = self.big_font.render(f"Score: {self.score}", True, (10, 10, 10))
        self.screen.blit(timer_txt, (ui_x, ui_y))
        self.screen.blit(level_txt, (ui_x + 220, ui_y))
        self.screen.blit(score_txt, (ui_x + 520, ui_y))

        # draw undo button
        # draw undo button (unlocked from level 2)
        undo_btn = pygame.Rect(preview_rect.right - 110, preview_rect.bottom - 50, 100, 36)
        if self.level >= 2 and self.undo_stack:
            pygame.draw.rect(self.screen, (80, 160, 80), undo_btn)
        else:
            pygame.draw.rect(self.screen, (160, 160, 160), undo_btn)
        undo_txt = self.font.render("Undo (U)", True, (255, 255, 255))
        self.screen.blit(undo_txt, (undo_btn.left + 10, undo_btn.top + 8))

        # draw shuffle (置换) button (unlocked from level 3)
        shuffle_btn = pygame.Rect(preview_rect.right - 230, preview_rect.bottom - 50, 110, 36)
        if self.level >= 3:
            pygame.draw.rect(self.screen, (100, 140, 200), shuffle_btn)
        else:
            pygame.draw.rect(self.screen, (160, 160, 160), shuffle_btn)
        sh_txt = self.font.render("Shuffle (R)", True, (255, 255, 255))
        self.screen.blit(sh_txt, (shuffle_btn.left + 10, shuffle_btn.top + 8))

        # rules text
        rules = [
            "Rules:",
            "- Click a top block in the upper grid to move it to the preview area",
            "- Only the last three items in preview (most recent 3) can be eliminated if identical",
            "- Example: if preview ends with AAA then those three are removed",
            "- Time per level: 3 minutes",
            "- Level 2 unlocks: Undo; Level 3 unlocks: Shuffle",
        ]
        for i, line in enumerate(rules):
            txt = self.font.render(line, True, (0, 0, 0))
            self.screen.blit(txt, (preview_rect.left + 10, ui_y + 50 + i * 22))

        # draw hint popup if needed (wrapped to avoid overflow)
        if getattr(self, 'hint_shown', False):
            if time.time() - self.hint_start < 4.0:
                hint_rect = pygame.Rect((WINDOW_WIDTH - 560) // 2, 80, 560, 72)
                pygame.draw.rect(self.screen, (255, 255, 200), hint_rect)
                pygame.draw.rect(self.screen, (120, 120, 120), hint_rect, 2)

                # render wrapped text to fit inside hint_rect with padding
                def render_wrapped(surface, text, font, color, rect, padding=12, line_spacing=2):
                    words = text.split()
                    lines = []
                    cur = ""
                    max_width = rect.width - padding * 2
                    for w in words:
                        test = cur + (" " if cur else "") + w
                        if font.size(test)[0] <= max_width:
                            cur = test
                        else:
                            if cur:
                                lines.append(cur)
                            cur = w
                    if cur:
                        lines.append(cur)

                    line_h = font.get_height()
                    total_h = len(lines) * line_h + max(0, len(lines) - 1) * line_spacing
                    y = rect.top + (rect.height - total_h) // 2
                    for line in lines:
                        txt_s = font.render(line, True, color)
                        x = rect.left + (rect.width - txt_s.get_width()) // 2
                        surface.blit(txt_s, (x, y))
                        y += line_h + line_spacing

                render_wrapped(self.screen, self.hint_msg, self.font, (0, 0, 0), hint_rect)
            else:
                self.hint_shown = False

        # draw victory overlay if active
        if getattr(self, 'victory_until', None):
            overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            self.screen.blit(overlay, (0, 0))
            msg = self.big_font.render("Congrats!", True, (255, 230, 100))
            sub = self.font.render("Advancing to next level...", True, (255, 255, 255))
            self.screen.blit(msg, ((WINDOW_WIDTH - msg.get_width()) // 2, (WINDOW_HEIGHT - msg.get_height()) // 2 - 10))
            self.screen.blit(sub, ((WINDOW_WIDTH - sub.get_width()) // 2, (WINDOW_HEIGHT - sub.get_height()) // 2 + 26))
        # draw times-up overlay if active (similar style to victory)
        if getattr(self, 'timesup_until', None):
            overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 200))
            self.screen.blit(overlay, (0, 0))
            msg = self.big_font.render("Time's up!", True, (255, 200, 200))
            sub = self.font.render("Restarting level...", True, (255, 255, 255))
            self.screen.blit(msg, ((WINDOW_WIDTH - msg.get_width()) // 2, (WINDOW_HEIGHT - msg.get_height()) // 2 - 10))
            self.screen.blit(sub, ((WINDOW_WIDTH - sub.get_width()) // 2, (WINDOW_HEIGHT - sub.get_height()) // 2 + 26))

        pygame.display.flip()

    def run(self):
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    # block input during victory or times-up overlay
                    if getattr(self, 'victory_until', None) or getattr(self, 'timesup_until', None):
                        continue
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_u:
                        # undo key
                        # Undo unlocked from level 2
                        if self.state == 'playing' and self.level >= 2 and self.undo_stack:
                            board_snap, prev_snap, score_snap, ts_snap = self.undo_stack.pop()
                            self.board = board_snap
                            self.preview = prev_snap
                            self.score = score_snap
                            self.level_start_ts = ts_snap
                    elif event.key == pygame.K_r:
                        # Shuffle / 置换 unlocked from level 3
                        if self.state == 'playing' and self.level >= 3:
                            # push snapshot for undo (so shuffle itself can be undone)
                            snap = (self._copy.deepcopy(self.board), list(self.preview), int(self.score), float(self.level_start_ts))
                            self.undo_stack.append(snap)
                            self.shuffle_remaining()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    # ignore mouse input during overlays
                    if getattr(self, 'victory_until', None) or getattr(self, 'timesup_until', None):
                        continue
                    mx, my = event.pos
                    # handle start/menu/gameover buttons
                    if self.state == 'menu':
                        btn_rect = pygame.Rect((WINDOW_WIDTH - 200) // 2, 220, 200, 60)
                        best_btn = pygame.Rect(btn_rect.left + (btn_rect.width - 120) // 2, btn_rect.bottom + 12, 120, 44)
                        if btn_rect.collidepoint(mx, my):
                            self.state = 'playing'
                            self.start_level(self.level)
                        elif best_btn.collidepoint(mx, my):
                            # show best-level popup for 2.5 seconds
                            self.showing_best_until = time.time() + 2.5
                        
                        continue
                    if self.state == 'gameover':
                        btn_rect = pygame.Rect((WINDOW_WIDTH - 300) // 2, 220, 300, 60)
                        if btn_rect.collidepoint(mx, my):
                            self.state = 'menu'
                        continue

                    # check undo button click
                    preview_top = int(WINDOW_HEIGHT * GRID_RATIO) + 10
                    preview_rect = pygame.Rect(10, preview_top, WINDOW_WIDTH - 20, WINDOW_HEIGHT - preview_top - 10)
                    undo_btn = pygame.Rect(preview_rect.right - 110, preview_rect.bottom - 50, 100, 36)
                    if undo_btn.collidepoint(mx, my) and self.state == 'playing' and self.level >= 2 and self.undo_stack:
                        board_snap, prev_snap, score_snap, ts_snap = self.undo_stack.pop()
                        self.board = board_snap
                        self.preview = prev_snap
                        self.score = score_snap
                        self.level_start_ts = ts_snap
                        continue

                    # check shuffle button click
                    shuffle_btn = pygame.Rect(preview_rect.right - 230, preview_rect.bottom - 50, 110, 36)
                    if shuffle_btn.collidepoint(mx, my) and self.state == 'playing' and self.level >= 3:
                        snap = (self._copy.deepcopy(self.board), list(self.preview), int(self.score), float(self.level_start_ts))
                        self.undo_stack.append(snap)
                        self.shuffle_remaining()
                        continue

                    self.handle_click(event.pos)

            self.update()
            self.draw()
            self.clock.tick(FPS)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("3D Stack Match Demo")
    game = Game(screen)
    game.run()
    pygame.quit()
    sys.exit(0)


if __name__ == '__main__':
    main()

