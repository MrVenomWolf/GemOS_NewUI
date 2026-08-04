# Gemini Desktop Assistant

A simple desktop chat app for Google's Gemini API, built with Python and Tkinter.
Styled like a dark IDE, with support for viewing code responses in boxed,
copyable code blocks and attaching local code/text files to your prompt.

## Features

- Chat with Gemini directly from a desktop window (no browser needed)
- Dark, IDE-inspired theme
- Code responses render in separate boxes with a language label and a Copy button
- Attach local files (`.py`, `.js`, `.java`, `.cpp`, and more) to include their
  contents in your message
- Runs on a background thread so the UI never freezes while waiting on a response

## Requirements

- Python 3.9+
- A Gemini API key — get one free at https://aistudio.google.com/apikey

## Setup

1. Clone this repo:
   ```
   git clone https://github.com/<your-username>/<your-repo>.git
   cd <your-repo>
   ```

2. Install the dependency:
   ```
   python -m pip install google-genai
   ```

3. Set your API key as an environment variable:

   **Windows (PowerShell):**
   ```
   $env:GEMINI_API_KEY="your_key_here"
   ```

   **Mac/Linux (bash):**
   ```
   export GEMINI_API_KEY="your_key_here"
   ```

   Alternatively, just run the app without setting this — it will prompt you
   for a key on launch instead.

4. Run the app:
   ```
   python pythongui.py
   ```

## Optional: Custom window icon

Drop a `.ico` file into the project folder and update the `ICON_PATH` constant
near the top of `pythongui.py` to point to it.

## Optional: Build a standalone .exe (Windows)

```
python -m pip install pyinstaller
pyinstaller --onefile --windowed --name GeminiAssistant pythongui.py
```

The built executable will appear in the `dist/` folder.

## Notes

- This project uses the `google-genai` SDK (not the older, deprecated
  `google-generativeai` package).
- Attached files are capped at 50,000 characters to avoid oversized requests;
  larger files get truncated with a note.

## License

MIT — feel free to fork and modify.
