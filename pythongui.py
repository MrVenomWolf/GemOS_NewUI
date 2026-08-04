
import google
from datetime import time
import os
import threading
import re
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog
 
from google import genai
from google.genai import types
 
# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY", "")   # or hardcode your key here
MODEL_NAME = "gemini-3.6-flash"                   # change to another model if you like
 
SYSTEM_INSTRUCTION = (
    "You are a helpful personal assistant. You help with general chat, "
    "coding questions, debugging, explaining concepts, and everyday tasks. "
    "Give clear, concise, and practical answers. When sharing code, use "
    "proper markdown code blocks.Also ask yourself do I need to write this line of excess code or can I use a shorter way."
)
 
 
THEME = {
    "bg":            "#1e1e1e",   # main background
    "bg_panel":      "#252526",   # side/input panel background
    "bg_input":      "#3c3c3c",   # text entry background
    "border":        "#3c3c3c",
    "text":          "#d4d4d4",   # default text
    "user":          "#569cd6",   # blue  - like keywords
    "assistant":     "#4ec9b0",   # teal/green - like types
    "system":        "#6a9955",   # green - like comments
    "accent":        "#007acc",   # VS Code blue accent (buttons)
    "accent_hover":  "#1177bb",
    "danger":        "#f14c4c",   # red for destructive actions
    "danger_hover":  "#d83a3a",
    "scrollbar":     "#424242",
    "code_bg":       "#0d1117",   # code block background (GitHub dark style)
    "code_header":   "#161b22",   # code block header strip
    "code_text":     "#e6edf3",
    "code_lang":     "#8b949e",
}
MONO_FONT = ("Consolas", 11)
MONO_FONT_BOLD = ("Consolas", 11, "bold")
MONO_FONT_ITALIC = ("Consolas", 9, "italic")
 
# Extension -> language label, used when a file is attached
EXT_LANGUAGE_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".jsx": "jsx",
    ".tsx": "tsx", ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
    ".cs": "csharp", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".html": "html", ".css": "css", ".json": "json", ".xml": "xml",
    ".yaml": "yaml", ".yml": "yaml", ".sql": "sql", ".sh": "bash",
    ".md": "markdown", ".txt": "text",
}
MAX_FILE_CHARS = 50_000  # safety cap so huge files don't blow up the request
 
 
class GeminiChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GemOS")
        self.root.geometry("900x650")
        self.root.minsize(500, 400)
        self.root.configure(bg=THEME["bg"])
        self.root.iconbitmap("blume_logo.ico")

       
 
        self.api_key = API_KEY
        self.client = None
        self.chat_session = None
        self.attached_file = None  # (filename, language, content) or None
 
        self._build_ui()
        self._init_model()
 
    # ---------------------------------------------------------------
    # UI SETUP
    # ---------------------------------------------------------------
    def _build_ui(self):
        # Title bar strip (purely decorative, IDE-style)
        title_bar = tk.Frame(self.root, bg=THEME["bg_panel"], height=32)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        tk.Label(
            title_bar, text="  ● gemini-chat.py — CTos",
            bg=THEME["bg_panel"], fg=THEME["system"], font=MONO_FONT, anchor="w"
        ).pack(fill=tk.X, padx=4, pady=6)
 
        # Chat display area
        self.chat_display = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            state="disabled",
            font=MONO_FONT,
            bg=THEME["bg"],
            fg=THEME["text"],
            insertbackground=THEME["text"],
            selectbackground="#264f78",
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
 
        # Color tags for user/assistant messages
        self.chat_display.tag_config("user", foreground=THEME["user"], font=MONO_FONT_BOLD)
        self.chat_display.tag_config("assistant", foreground=THEME["assistant"], font=MONO_FONT_BOLD)
        self.chat_display.tag_config("system", foreground=THEME["system"], font=MONO_FONT_ITALIC)
        self.chat_display.tag_config("body", foreground=THEME["text"], font=MONO_FONT)
 
        # Bottom input panel
        input_frame = tk.Frame(self.root, bg=THEME["bg_panel"])
        input_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=0, pady=0)
 
        inner_pad = tk.Frame(input_frame, bg=THEME["bg_panel"])
        inner_pad.pack(fill=tk.X, padx=10, pady=10)
 
        # Attachment chip — hidden until a file is attached
        self.attachment_row = tk.Frame(input_frame, bg=THEME["bg_panel"])
        self.attachment_label = tk.Label(
            self.attachment_row, text="", bg=THEME["bg_input"], fg=THEME["assistant"],
            font=("Consolas", 9), anchor="w", padx=8, pady=3,
        )
        self.attachment_label.pack(side=tk.LEFT, padx=(0, 6))
        self.attachment_remove_btn = tk.Button(
            self.attachment_row, text="✕", font=("Consolas", 9),
            bg=THEME["bg_input"], fg=THEME["danger"], relief=tk.FLAT,
            borderwidth=0, cursor="hand2", command=self._clear_attachment,
        )
        self.attachment_remove_btn.pack(side=tk.LEFT)
        # Not packed into input_frame yet — shown only once a file is attached
 
        self.entry = tk.Text(
            inner_pad,
            height=3,
            font=MONO_FONT,
            wrap=tk.WORD,
            bg=THEME["bg_input"],
            fg=THEME["text"],
            insertbackground=THEME["text"],
            selectbackground="#264f78",
            relief=tk.FLAT,
            borderwidth=0,
            padx=8,
            pady=8,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["accent"],
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry.bind("<Return>", self._on_enter_key)
        self.entry.bind("<Shift-Return>", lambda e: None)  # allow newline with Shift+Enter
 
        btn_frame = tk.Frame(inner_pad, bg=THEME["bg_panel"])
        btn_frame.pack(side=tk.RIGHT)
 
        self.send_btn = tk.Button(
            btn_frame, text="Send  ▶", width=10, command=self.send_message,
            bg=THEME["accent"], fg="#ffffff", activebackground=THEME["accent_hover"],
            activeforeground="#ffffff", relief=tk.FLAT, borderwidth=0,
            font=MONO_FONT, cursor="hand2",
        )
        self.send_btn.pack(pady=(0, 6), ipady=4)
 
        self.attach_btn = tk.Button(
            btn_frame, text="📎 Attach", width=10, command=self._attach_file,
            bg=THEME["bg_input"], fg=THEME["text"], activebackground=THEME["accent"],
            activeforeground="#ffffff", relief=tk.FLAT, borderwidth=0,
            font=("Consolas", 10), cursor="hand2",
        )
        self.attach_btn.pack(pady=(0, 6), ipady=4)
 
        self.clear_btn = tk.Button(
            btn_frame, text="Clear", width=10, command=self.clear_chat,
            bg=THEME["bg_input"], fg=THEME["text"], activebackground=THEME["danger"],
            activeforeground="#ffffff", relief=tk.FLAT, borderwidth=0,
            font=MONO_FONT, cursor="hand2",
        )
        self.clear_btn.pack(ipady=4)
 
        self.entry.focus_set()
 
    # ---------------------------------------------------------------
    # MODEL SETUP
    # ---------------------------------------------------------------
    def _init_model(self):
        if not self.api_key:
            self.api_key = simpledialog.askstring(
                "API Key Required",
                "Enter your Gemini API key:",
                show="*",
            )
        if not self.api_key:
            messagebox.showerror("Error", "No API key provided. Exiting.")
            self.root.destroy()
            return
 
        try:
            self.client = genai.Client(api_key=self.api_key)
            self.chat_session = self.client.chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
            )
            self._append_message("system", f"Connected to {MODEL_NAME}. You can now start talking .")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to initialize Gemini:\n{e}")
 
    # ---------------------------------------------------------------
    # FILE ATTACHMENTS
    # ---------------------------------------------------------------
    def _attach_file(self):
        path = filedialog.askopenfilename(
            title="Select a file to attach",
            filetypes=[
                ("Code & text files", " ".join(f"*{ext}" for ext in EXT_LANGUAGE_MAP)),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
 
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file:\n{e}")
            return
 
        truncated = False
        if len(content) > MAX_FILE_CHARS:
            content = content[:MAX_FILE_CHARS]
            truncated = True
 
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1].lower()
        language = EXT_LANGUAGE_MAP.get(ext, "text")
 
        self.attached_file = (filename, language, content, truncated)
 
        chip_text = f"📎 {filename}" + ("  (truncated)" if truncated else "")
        self.attachment_label.config(text=chip_text)
        self.attachment_row.pack(fill=tk.X, padx=10, pady=(0, 0))
 
    def _clear_attachment(self):
        self.attached_file = None
        self.attachment_row.pack_forget()
 
    # ---------------------------------------------------------------
    # MESSAGE HANDLING
    # ---------------------------------------------------------------
    def _on_enter_key(self, event):
        # Enter sends the message; Shift+Enter adds a newline
        if not (event.state & 0x0001):  # 0x0001 = Shift key mask
            self.send_message()
            return "break"
 
    def send_message(self):
        user_text = self.entry.get("1.0", tk.END).strip()
        if not user_text and not self.attached_file:
            return
        self.entry.delete("1.0", tk.END)
 
        attachment = self.attached_file
        self._clear_attachment()
 
        # Show the typed text (or a default note if only a file was sent)
        shown_text = user_text if user_text else "Please review this file."
        self._append_message("user", shown_text)
 
        # Build what actually gets sent to Gemini, and render the attachment
        # as its own code block directly (NOT by embedding markdown fences into
        # plain text and re-parsing them) — if the attached file itself contains
        # ``` sequences (e.g. you attach this very script), regex-based fence
        # parsing would break and leak raw text into the chat log.
        payload_text = user_text
        if attachment:
            filename, language, file_content, truncated = attachment
            note = f"[Attached file: {filename}]" + (" (truncated)" if truncated else "")
            self._append_attachment_block(note, language, file_content)
            fence = f"{note}\n```{language}\n{file_content}\n```"
            payload_text = (user_text + "\n\n" + fence) if user_text else fence
 
        self.send_btn.config(state="disabled")
 
        # Run the API call in a background thread so the GUI doesn't freeze
        threading.Thread(target=self._get_response, args=(payload_text,), daemon=True).start()
 
    def _append_attachment_block(self, note, language, content):
        """Render an attached file's code directly as a code box, bypassing
        the markdown-fence regex parser entirely."""
        self.chat_display.config(state="normal")
        self.chat_display.insert(tk.END, f"{note}\n", "system")
        self._insert_code_block(language, content)
        self.chat_display.config(state="disabled")
        self.chat_display.see(tk.END)
 
    def _get_response(self, user_text):
        try:
            response = self.chat_session.send_message(user_text)
            reply = response.text
        except Exception as e:
            reply = f"[Error contacting Gemini: {e}]"
 
        # Update the GUI back on the main thread
        self.root.after(0, self._append_message, "assistant", reply)
        self.root.after(0, lambda: self.send_btn.config(state="normal"))
 
    _CODE_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
 
    def _append_message(self, role, text):
        self.chat_display.config(state="normal")
        label = {"user": "You", "assistant": "Gemini", "system": "System"}[role]
        self.chat_display.insert(tk.END, f"\n{label}:\n", role)
 
        # Split the message into alternating plain-text / code segments
        pos = 0
        for match in self._CODE_FENCE_RE.finditer(text):
            plain = text[pos:match.start()]
            if plain.strip("\n"):
                self.chat_display.insert(tk.END, plain, "body")
            language = match.group(1) or "code"
            code = match.group(2).rstrip("\n")
            self._insert_code_block(language, code)
            pos = match.end()
 
        remainder = text[pos:]
        if remainder:
            self.chat_display.insert(tk.END, remainder + "\n", "body")
 
        self.chat_display.config(state="disabled")
        self.chat_display.see(tk.END)
 
    def _insert_code_block(self, language, code):
        """Embed a styled code box (header + copy button + code) inline in the chat log."""
        container = tk.Frame(self.chat_display, bg=THEME["border"], bd=0)
 
        # Header strip: language label + copy button
        header = tk.Frame(container, bg=THEME["code_header"])
        header.pack(fill=tk.X)
 
        tk.Label(
            header, text=f"  {language}", bg=THEME["code_header"], fg=THEME["code_lang"],
            font=("Consolas", 9), anchor="w"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)
 
        copy_btn = tk.Button(
            header, text="Copy", font=("Consolas", 9),
            bg=THEME["code_header"], fg=THEME["code_lang"],
            activebackground=THEME["accent"], activeforeground="#ffffff",
            relief=tk.FLAT, borderwidth=0, cursor="hand2", padx=8,
            command=lambda: self._copy_to_clipboard(code, copy_btn),
        )
        copy_btn.pack(side=tk.RIGHT, padx=4, pady=2)
 
        # Code body — a read-only Text widget sized to fit its content
        line_count = code.count("\n") + 1
        code_box = tk.Text(
            container,
            wrap=tk.NONE,
            font=("Consolas", 10),
            bg=THEME["code_bg"],
            fg=THEME["code_text"],
            insertbackground=THEME["code_text"],
            selectbackground="#264f78",
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=8,
            height=min(line_count, 25),
        )
        code_box.insert("1.0", code)
        code_box.config(state="disabled")
        code_box.pack(fill=tk.X)
 
        # Embed the whole block into the chat log as a window
        self.chat_display.window_create(tk.END, window=container, stretch=True)
        self.chat_display.insert(tk.END, "\n")
 
    def _copy_to_clipboard(self, code, button):
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        original_text = button.cget("text")
        button.config(text="Copied!")
        self.root.after(1200, lambda: button.config(text=original_text))
 
    def clear_chat(self):
        if not messagebox.askyesno("Clear Chat", "Clear the conversation history?"):
            return
        self.chat_display.config(state="normal")
        self.chat_display.delete("1.0", tk.END)
        self.chat_display.config(state="disabled")
        self.chat_session = self.client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
            ),
        )
        self._append_message("system", "Chat cleared. New session started.")
 
 
if __name__ == "__main__":
    root = tk.Tk()
    app = GeminiChatApp(root)
    root.mainloop()