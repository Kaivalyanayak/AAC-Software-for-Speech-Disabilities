
import tkinter as tk
from tkinter import messagebox
import threading
import hashlib
import json
import os

import pygame

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PHRASE_FILE = os.path.join(APP_DIR, "saved_phrases.json")
AUDIO_CACHE_DIR = os.path.join(APP_DIR, "audio_cache")

DEFAULT_CATEGORIES = {
    "Greetings": ["Hello", "Hi", "How are you?"],
    "Feelings": ["Happy", "Sad", "Tired"],
    "Requests": ["Drink", "Eat", "Help"],
    "Activities": ["Play", "Read", "Watch"],
}

EMERGENCY_PHRASE = "I need help immediately"

# ---------------------------------------------------------------------------
# Palette - muted, warm tones instead of saturated primaries.
# Each category gets its own (background, border, text, glyph) so cards
# are distinguishable at a glance without relying on color alone.
# ---------------------------------------------------------------------------
PALETTE = {
    "app_bg": "#F4F1EC",
    "card_bg": "#FFFFFF",
    "card_border": "#E4E0D8",
    "text_primary": "#2B2A27",
    "text_secondary": "#75726A",
    "status_text": "#8A8377",
    "stop_bg": "#ECEAE4",
    "stop_text": "#5C5A54",
    "emergency_bg": "#C0463B",
    "emergency_bg_active": "#A53A30",
    "emergency_text": "#FFFFFF",
    "add_bg": "#5C7A5E",
    "add_bg_active": "#4D6750",
    "add_text": "#FFFFFF",
    "input_bg": "#FFFFFF",
    "input_border": "#D8D4CB",
    "speaking_bg": "#E9F1E9",
    "speaking_border": "#5C7A5E",
}

CATEGORY_STYLE = {
    "Greetings": {"bg": "#E3EFE9", "border": "#9FC2AE", "text": "#2F5B45", "glyph": "\u270B"},
    "Feelings":  {"bg": "#F3E7DE", "border": "#D9A97D", "text": "#7A4A23", "glyph": "\u263A"},
    "Requests":  {"bg": "#E9E5F2", "border": "#B5A6D6", "text": "#4B3B72", "glyph": "\u270C"},
    "Activities": {"bg": "#F2E4E9", "border": "#D9A0B7", "text": "#7A3550", "glyph": "\u2699"},
    "Custom":    {"bg": "#E4ECF2", "border": "#9DBBD6", "text": "#2C4D6E", "glyph": "\u270E"},
}


def phrase_to_cache_path(phrase: str) -> str:
    """Map a phrase to a stable filename so repeated phrases reuse the
    same cached audio file instead of re-downloading or colliding."""
    digest = hashlib.sha256(phrase.strip().lower().encode("utf-8")).hexdigest()
    return os.path.join(AUDIO_CACHE_DIR, f"{digest}.mp3")


def round_rect_points(x1, y1, x2, y2, r):
    """Coordinate list for a rounded rectangle, used with create_polygon
    (smooth=True) on a Canvas, since Tkinter has no native rounded-rect
    widget or rounded button styling."""
    return [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]


def shade_hex(hex_color, delta):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r = max(0, min(255, r + delta))
    g = max(0, min(255, g + delta))
    b = max(0, min(255, b + delta))
    return f"#{r:02x}{g:02x}{b:02x}"


class RoundedCard(tk.Canvas):
    """A clickable rounded-rectangle 'card' with a glyph and label,
    used for the category grid. Plain tk.Button corners can't be
    rounded, so this draws its own background and binds click events."""

    def __init__(self, parent, glyph, text, bg, border, fg, command, bg_parent=None, **kwargs):
        super().__init__(parent, highlightthickness=0,
                          bg=bg_parent if bg_parent is not None else parent["bg"],
                          **kwargs)
        self.command = command
        self.bg_color = bg
        self.border_color = border
        self.fg_color = fg
        self.glyph = glyph
        self.text = text
        self._normal_bg = bg
        self._hover_bg = shade_hex(bg, -8)

        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return
        r = 16
        pts = round_rect_points(2, 2, w - 2, h - 2, r)
        self.create_polygon(pts, smooth=True, fill=self._normal_bg,
                             outline=self.border_color, width=1)
        self.create_text(w // 2, h // 2 - 12, text=self.glyph,
                          font=("Segoe UI Symbol", 20), fill=self.fg_color)
        self.create_text(w // 2, h // 2 + 18, text=self.text,
                          font=("Arial", 13, "bold"), fill=self.fg_color)

    def _on_click(self, event):
        if self.command:
            self.command()

    def _on_enter(self, event):
        self._normal_bg = self._hover_bg
        self._redraw()
        self.configure(cursor="hand2")

    def _on_leave(self, event):
        self._normal_bg = self.bg_color
        self._redraw()


class PillButton(tk.Canvas):
    """A rounded pill-shaped button, used for Stop / Emergency / Add,
    since tk.Button cannot render rounded corners."""

    def __init__(self, parent, text, bg, fg, command, active_bg=None,
                 font=("Arial", 13, "bold"), glyph=None, bg_parent=None, **kwargs):
        super().__init__(parent, highlightthickness=0,
                          bg=bg_parent if bg_parent is not None else parent["bg"],
                          **kwargs)
        self.text = text
        self.bg_color = bg
        self.active_bg = active_bg or bg
        self.fg_color = fg
        self.command = command
        self.font = font
        self.glyph = glyph
        self._current_bg = bg

        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._set_bg(self.active_bg))
        self.bind("<Leave>", lambda e: self._set_bg(self.bg_color))

    def _set_bg(self, color):
        self._current_bg = color
        self._redraw()
        self.configure(cursor="hand2")

    def _redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return
        r = h / 2
        pts = round_rect_points(2, 2, w - 2, h - 2, r)
        self.create_polygon(pts, smooth=True, fill=self._current_bg, outline="")
        label = f"{self.glyph}  {self.text}" if self.glyph else self.text
        self.create_text(w // 2, h // 2, text=label, font=self.font, fill=self.fg_color)

    def _on_click(self, event):
        if self.command:
            self.command()


class AACSoftware:

    def __init__(self, root):
        self.root = root
        self.root.title("AAC Software")
        self.root.geometry("760x840")
        self.root.minsize(560, 680)
        self.root.configure(bg=PALETTE["app_bg"])

        os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
        pygame.mixer.init()

        self.categories = {}
        self.load_saved_phrases()

        self._currently_speaking = False
        self._poll_job = None
        self._active_phrase_rows = {}
        self._speaking_text = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = tk.Frame(self.root, bg=PALETTE["app_bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=28, pady=24)

        header = tk.Frame(outer, bg=PALETTE["app_bg"])
        header.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            header,
            text="Let's talk",
            font=("Arial", 24, "bold"),
            bg=PALETTE["app_bg"],
            fg=PALETTE["text_primary"],
        ).pack(anchor="center")

        tk.Label(
            header,
            text="Tap a category, then a phrase",
            font=("Arial", 12),
            bg=PALETTE["app_bg"],
            fg=PALETTE["text_secondary"],
        ).pack(anchor="center", pady=(2, 0))

        if not GTTS_AVAILABLE:
            tk.Label(
                outer,
                text="Note: gTTS isn't installed, so new phrases can't be "
                     "spoken until it is. Previously cached phrases still work.",
                font=("Arial", 9),
                bg=PALETTE["app_bg"],
                fg="#9A6B33",
                wraplength=680,
                justify="center",
            ).pack(pady=(8, 0))

        self.status_label = tk.Label(
            outer,
            text=" ",
            font=("Arial", 11, "italic"),
            bg=PALETTE["app_bg"],
            fg=PALETTE["status_text"],
        )
        self.status_label.pack(pady=(10, 6))

        self._build_category_grid(outer)
        self._build_custom_input(outer)
        self._build_action_row(outer)

    def _build_category_grid(self, parent):
        grid = tk.Frame(parent, bg=PALETTE["app_bg"])
        grid.pack(fill=tk.X, pady=(8, 18))

        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform="cat")

        built_in = [c for c in self.categories if c != "Custom"]
        for i, category in enumerate(built_in):
            style = CATEGORY_STYLE.get(category, CATEGORY_STYLE["Custom"])
            card = RoundedCard(
                grid,
                glyph=style["glyph"],
                text=category,
                bg=style["bg"],
                border=style["border"],
                fg=style["text"],
                command=lambda c=category: self.show_phrases(c, deletable=False),
                bg_parent=PALETTE["app_bg"],
                height=92,
            )
            row, col = divmod(i, 2)
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)

        custom_style = CATEGORY_STYLE["Custom"]
        custom_card = RoundedCard(
            grid,
            glyph=custom_style["glyph"],
            text="Custom phrases",
            bg=custom_style["bg"],
            border=custom_style["border"],
            fg=custom_style["text"],
            command=lambda: self.show_phrases("Custom", deletable=True),
            bg_parent=PALETTE["app_bg"],
            height=64,
        )
        next_row = (len(built_in) + 1) // 2
        custom_card.grid(row=next_row, column=0, columnspan=2, sticky="nsew", padx=6, pady=6)

    def _build_custom_input(self, parent):
        wrap = tk.Frame(parent, bg=PALETTE["card_bg"], highlightbackground=PALETTE["card_border"],
                         highlightthickness=1)
        wrap.pack(fill=tk.X, pady=(0, 16), ipady=8, ipadx=10)

        row = tk.Frame(wrap, bg=PALETTE["card_bg"])
        row.pack(fill=tk.X, padx=4)

        self.custom_entry = tk.Entry(
            row,
            font=("Arial", 13),
            bg=PALETTE["input_bg"],
            fg=PALETTE["text_primary"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["input_border"],
            highlightcolor=PALETTE["add_bg"],
        )
        self.custom_entry.pack(side="left", fill=tk.X, expand=True, ipady=8, padx=(2, 10))
        self._add_placeholder(self.custom_entry, "Type a custom phrase...")
        self.custom_entry.bind("<Return>", lambda e: self.add_custom_phrase())

        add_btn = PillButton(
            row,
            text="Add",
            bg=PALETTE["add_bg"],
            active_bg=PALETTE["add_bg_active"],
            fg=PALETTE["add_text"],
            command=self.add_custom_phrase,
            bg_parent=PALETTE["card_bg"],
            width=90,
            height=38,
        )
        add_btn.pack(side="right")

    def _add_placeholder(self, entry, placeholder):
        entry.placeholder = placeholder
        entry.config(fg=PALETTE["text_secondary"])
        entry.insert(0, placeholder)

        def on_focus_in(event):
            if entry.get() == placeholder:
                entry.delete(0, tk.END)
                entry.config(fg=PALETTE["text_primary"])

        def on_focus_out(event):
            if not entry.get():
                entry.insert(0, placeholder)
                entry.config(fg=PALETTE["text_secondary"])

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def _build_action_row(self, parent):
        row = tk.Frame(parent, bg=PALETTE["app_bg"])
        row.pack(fill=tk.X)

        stop_btn = PillButton(
            row,
            text="Stop",
            glyph="\u23F9",
            bg=PALETTE["stop_bg"],
            active_bg=shade_hex(PALETTE["stop_bg"], -10),
            fg=PALETTE["stop_text"],
            command=self.stop_speaking,
            bg_parent=PALETTE["app_bg"],
            height=52,
        )
        stop_btn.pack(side="left", fill=tk.X, expand=True, padx=(0, 8))

        emergency_btn = PillButton(
            row,
            text="Emergency help",
            glyph="\u26A0",
            bg=PALETTE["emergency_bg"],
            active_bg=PALETTE["emergency_bg_active"],
            fg=PALETTE["emergency_text"],
            command=lambda: self.speak(EMERGENCY_PHRASE),
            font=("Arial", 14, "bold"),
            bg_parent=PALETTE["app_bg"],
            height=52,
        )
        emergency_btn.pack(side="left", fill=tk.X, expand=True, padx=(8, 0))

    # ------------------------------------------------------------------
    # Custom phrase management
    # ------------------------------------------------------------------

    def add_custom_phrase(self):
        phrase = self.custom_entry.get().strip()

        if not phrase or phrase == getattr(self.custom_entry, "placeholder", None):
            messagebox.showwarning("Warning", "Please enter a phrase.")
            return

        if phrase in self.categories["Custom"]:
            messagebox.showinfo("Already saved", "That phrase is already saved.")
            self.custom_entry.delete(0, tk.END)
            return

        self.categories["Custom"].append(phrase)
        self.save_phrases()
        messagebox.showinfo("Success", "Phrase saved!")
        self.custom_entry.delete(0, tk.END)

        threading.Thread(target=self._ensure_cached, args=(phrase,), daemon=True).start()

    def delete_custom_phrase(self, phrase, window):
        if phrase in self.categories["Custom"]:
            self.categories["Custom"].remove(phrase)
            self.save_phrases()
        window.destroy()
        self.show_phrases("Custom", deletable=True)

    # ------------------------------------------------------------------
    # Phrase list window
    # ------------------------------------------------------------------

    def show_phrases(self, category_name, deletable):
        phrases = self.categories[category_name]
        style = CATEGORY_STYLE.get(category_name, CATEGORY_STYLE["Custom"])

        window = tk.Toplevel(self.root)
        window.title(category_name)
        window.geometry("560x520")
        window.configure(bg=PALETTE["app_bg"])

        header = tk.Frame(window, bg=style["bg"])
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=f"{style['glyph']}  {category_name}",
            font=("Arial", 16, "bold"),
            bg=style["bg"],
            fg=style["text"],
        ).pack(pady=14)

        canvas = tk.Canvas(window, bg=PALETTE["app_bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(window, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg=PALETTE["app_bg"])

        frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        self._active_phrase_rows = {}

        if not phrases:
            tk.Label(
                frame,
                text="No phrases yet.",
                font=("Arial", 13, "italic"),
                bg=PALETTE["app_bg"],
                fg=PALETTE["text_secondary"],
            ).pack(pady=24, padx=15)

        for phrase in phrases:
            row_wrap = tk.Frame(frame, bg=PALETTE["card_bg"],
                                 highlightbackground=PALETTE["card_border"],
                                 highlightthickness=1)
            row_wrap.pack(fill=tk.X, padx=18, pady=6)
            self._active_phrase_rows[phrase] = row_wrap

            inner = tk.Frame(row_wrap, bg=PALETTE["card_bg"], cursor="hand2")
            inner.pack(fill=tk.X, padx=12, pady=10)

            label = tk.Label(
                inner,
                text=phrase,
                font=("Arial", 14),
                bg=PALETTE["card_bg"],
                fg=PALETTE["text_primary"],
                anchor="w",
                cursor="hand2",
            )
            label.pack(side="left", fill=tk.X, expand=True)

            speak_glyph = tk.Label(
                inner,
                text="\u266A",
                font=("Arial", 14),
                bg=PALETTE["card_bg"],
                fg=PALETTE["text_secondary"],
                cursor="hand2",
            )
            speak_glyph.pack(side="right", padx=(8, 0))

            for widget in (inner, label, speak_glyph):
                widget.bind("<Button-1>", lambda e, p=phrase: self.speak(p))

            if deletable:
                del_btn = tk.Label(
                    inner,
                    text="Delete",
                    font=("Arial", 10, "bold"),
                    bg=PALETTE["card_bg"],
                    fg=PALETTE["emergency_bg"],
                    cursor="hand2",
                )
                del_btn.pack(side="right", padx=(8, 10))
                del_btn.bind("<Button-1>", lambda e, p=phrase: self.delete_custom_phrase(p, window))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _highlight_phrase_row(self, phrase, active):
        row = self._active_phrase_rows.get(phrase)
        if row is None or not row.winfo_exists():
            return
        target_bg = PALETTE["speaking_bg"] if active else PALETTE["card_bg"]
        target_border = PALETTE["speaking_border"] if active else PALETTE["card_border"]
        row.configure(bg=target_bg, highlightbackground=target_border)
        self._recolor_children(row, target_bg)

    def _recolor_children(self, widget, bg):
        for child in widget.winfo_children():
            try:
                child.configure(bg=bg)
            except tk.TclError:
                pass
            self._recolor_children(child, bg)

    # ------------------------------------------------------------------
    # Speech: offline-first caching + non-blocking playback
    # ------------------------------------------------------------------

    def _ensure_cached(self, phrase):
        cache_path = phrase_to_cache_path(phrase)

        if os.path.exists(cache_path):
            return cache_path

        if not GTTS_AVAILABLE:
            return None

        try:
            tmp_path = cache_path + ".tmp"
            tts = gTTS(text=phrase, lang="en")
            tts.save(tmp_path)
            os.replace(tmp_path, cache_path)
            return cache_path
        except Exception:
            return None

    def speak(self, text):
        if not text:
            return

        self._set_status(f"Preparing: \u201c{text}\u201d")
        self._highlight_phrase_row(text, True)
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def _speak_worker(self, text):
        cache_path = self._ensure_cached(text)

        if cache_path is None:
            self.root.after(0, self._on_speak_unavailable, text)
            return

        self.root.after(0, self._play_audio, cache_path, text)

    def _on_speak_unavailable(self, text):
        self._set_status(" ")
        self._highlight_phrase_row(text, False)
        if GTTS_AVAILABLE:
            messagebox.showinfo(
                "Can't speak that yet",
                f"\u201c{text}\u201d isn't saved for offline use yet, and there's no "
                "internet connection right now to generate it. Try again "
                "once you're back online.",
            )
        else:
            messagebox.showinfo(
                "Speech unavailable",
                f"\u201c{text}\u201d hasn't been cached, and the text-to-speech "
                "library isn't installed, so it can't be generated.",
            )

    def _play_audio(self, path, text):
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self._currently_speaking = True
            self._speaking_text = text
            self._set_status(f"Speaking: \u201c{text}\u201d")
            self._poll_playback()
        except Exception as e:
            self._set_status(" ")
            self._highlight_phrase_row(text, False)
            messagebox.showerror("Playback error", str(e))

    def _poll_playback(self):
        if pygame.mixer.music.get_busy():
            self._poll_job = self.root.after(100, self._poll_playback)
        else:
            self._currently_speaking = False
            self._poll_job = None
            self._set_status(" ")
            if self._speaking_text:
                self._highlight_phrase_row(self._speaking_text, False)

    def stop_speaking(self):
        if self._currently_speaking:
            pygame.mixer.music.stop()
            self._currently_speaking = False
            if self._speaking_text:
                self._highlight_phrase_row(self._speaking_text, False)
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
            self._poll_job = None
        self._set_status(" ")

    def _set_status(self, text):
        self.status_label.config(text=text)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_phrases(self):
        with open(PHRASE_FILE, "w") as f:
            json.dump(self.categories["Custom"], f)

    def load_saved_phrases(self):
        if os.path.exists(PHRASE_FILE):
            try:
                with open(PHRASE_FILE, "r") as f:
                    custom_phrases = json.load(f)
                if not isinstance(custom_phrases, list):
                    custom_phrases = []
            except (json.JSONDecodeError, OSError):
                custom_phrases = []
        else:
            custom_phrases = []

        self.categories = {**DEFAULT_CATEGORIES, "Custom": custom_phrases}


if __name__ == "__main__":
    root = tk.Tk()
    app = AACSoftware(root)
    root.mainloop()
