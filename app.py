import tkinter as tk
from tkinter import ttk
from deep_translator import GoogleTranslator
from syrics.api import Spotify
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pickle
import os
import sv_ttk

# Initialize Spotify API
sp = Spotify("AQBguCOYKspUu2civycPjuJwh4anoCj2zYJrY_1sIn9tigRXklrI6Blx4IMBEgH9Ec_FYzNYUIRhCphhzjHQ8fMYinaVYRU1Df_UhIQuzNDG6cTNHe3hrvi6E3MNW6hbScuFLCHVE6S4m_Y7x4yH0JyRK66C0QTaQknOZJLoR7c3yXUveROsf3Pp-zaWm1WUWQRTwJ7L3Ps1uwZxLYs")

# Global configuration
CACHE_FILE = 'lyrics_cache.pkl'
MAX_CACHE_SIZE = 1000
DEBUG_MODE = False
USE_CACHE = True
USE_THREADING = False

# Global state
current_song_id = None
translation_complete = False
translated_lyrics_cache = None
language = ""
translated_song_name = None
streaming_mode = True  # New global variable to control streaming mode

def debug_print(*args, **kwargs):
    if DEBUG_MODE:
        print(*args, **kwargs)

# Load cache from file if it exists
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        lyrics_cache = pickle.load(f)
else:
    lyrics_cache = {}

# Function to save cache to file
def save_cache():
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(lyrics_cache, f)

# Function to get the current song and playback position
def get_current_playback_position():
    try:
        current_song = sp.get_current_song()
        position_ms = current_song['progress_ms']
        return current_song, position_ms
    except Exception as e:
        print(f"Error fetching current song playback position: {e}")
        return None, 0

# Function to update the Treeview and the current time label
def update_display():
    global current_song_id
    current_song, current_position = get_current_playback_position()
    if current_song:
        song_id = current_song['item']['id']
        if song_id != current_song_id:
            current_song_id = song_id
            update_lyrics()

        current_time_label.config(text=f"Current Time: {ms_to_min_sec(current_position)}")
        last_index = None
        for item in tree.get_children():
            item_data = tree.item(item)
            start_time = int(item_data['values'][0].split(":")[0]) * 60000 + int(item_data['values'][0].split(":")[1]) * 1000
            if start_time <= current_position:
                last_index = item
            else:
                break
        if last_index:
            tree.selection_set(last_index)
            tree.see(last_index)

    root.after(500, update_display)  # Reduced the update frequency

# Function to convert milliseconds to minutes:seconds format
def ms_to_min_sec(ms):
    ms = int(ms)
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    return f"{minutes}:{seconds:02}"

# Function to translate a single lyric line
def translate_line(translator, line):
    original_text = line['words']
    timestamp = line['startTimeMs']
    # Create a unique ID combining timestamp and text
    line_id = f"{timestamp}_{hash(original_text)}"
    try:
        debug_print(f"\n[{ms_to_min_sec(timestamp)}] [{line_id}] Translating: '{original_text}'")
        translated_text = translator.translate(original_text)
        debug_print(f"[{ms_to_min_sec(timestamp)}] [{line_id}] Result: '{translated_text}'")
        return {
            'startTimeMs': timestamp,
            'words': original_text,
            'translated': translated_text,
            'line_id': line_id
        }
    except Exception as e:
        debug_print(f"[{ms_to_min_sec(timestamp)}] [{line_id}] Error translating '{original_text}': {e}")
        return {
            'startTimeMs': timestamp,
            'words': original_text,
            'translated': original_text,
            'line_id': line_id
        }

# Function to translate lyrics using multithreading
def translate_words(lyrics, song_name, song_id, callback):
    global translation_complete, translated_lyrics_cache, use_cache, translated_song_name
    debug_print(f"\nTranslating {len(lyrics)} lines for: {song_name}")
    debug_print(f"Mode: {'multi-threaded' if USE_THREADING else 'single-threaded'}")
    
    translator = GoogleTranslator(source='auto', target='en')
    translated_song_name = translator.translate(song_name)
    debug_print(f"Translated song name: '{song_name}' -> '{translated_song_name}'")
    
    if USE_THREADING:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = list(map(lambda line: executor.submit(translate_line, translator, line), lyrics))
            results = [future.result() for future in futures]
        translated_lyrics = sorted(results, key=lambda x: x['startTimeMs'])
    else:
        results = []
        for line in lyrics:
            result = translate_line(translator, line)
            results.append(result)
        translated_lyrics = results
        debug_print(f"results: {results}")
    
    debug_print(f"\nTranslation complete. First few results:")
    for i, lyric in enumerate(translated_lyrics[:5]):
        timestamp = ms_to_min_sec(lyric['startTimeMs'])
        debug_print(f"{i+1}. [{timestamp}]")
        debug_print(f"   Line ID: {lyric['line_id']}")
        debug_print(f"   Original: '{lyric['words']}'")
        debug_print(f"   Translated: '{lyric['translated']}'")
    debug_print("...")

    if USE_CACHE:
        debug_print("Updating cache...")
        lyrics_cache[song_id] = translated_lyrics
        if len(lyrics_cache) > MAX_CACHE_SIZE:
            lyrics_cache.pop(next(iter(lyrics_cache)))
        save_cache()
    else:
        debug_print("Cache updates disabled")
        
    callback(translated_lyrics)
    translation_complete = True

# Function to update the lyrics in the Treeview
def update_lyrics():
    global current_song_id, translation_complete, translated_song_name

    current_song = sp.get_current_song()
    song_id = current_song['item']['id']
    song_name = current_song['item']['name']
    debug_print(f"\n=== Processing: {song_name} ===")
    
    lyrics = sp.get_lyrics(song_id)
    lyrics_data = lyrics['lyrics']['lines'] if lyrics and 'lyrics' in lyrics and 'lines' in lyrics['lyrics'] else None

    tree.delete(*tree.get_children())
    root.title(song_name)  # Set initial title

    if lyrics_data:
        detected_lang = lyrics['lyrics']['language']
        global language
        language = detected_lang
        debug_print(f"Detected language: {detected_lang}")
        tree.heading("Original Lyrics", text=f"Original Lyrics ({detected_lang})")

        for index, lyric in enumerate(lyrics_data):
            tree.insert("", "end", values=(ms_to_min_sec(lyric['startTimeMs']), lyric['words'], ""))
        
        translation_complete = False
        if USE_CACHE and song_id in lyrics_cache:
            debug_print(f"Using cached translation for {song_id}")
            cached_lyrics = lyrics_cache[song_id]
            update_translations(cached_lyrics)
            # Get translated name from cache if available
            if cached_lyrics and len(cached_lyrics) > 0:
                translator = GoogleTranslator(source='auto', target='en')
                translated_song_name = translator.translate(song_name)
                root.title(f"{song_name}: {translated_song_name}")
        else:
            debug_print(f"Starting new translation for {song_id}")
            if streaming_mode:
                # Start streaming translation for each line
                for line in lyrics_data:
                    threading.Thread(
                        target=stream_translate_line,
                        args=(line, song_name, song_id)
                    ).start()
            else:
                # Use the original batch translation method
                threading.Thread(
                    target=translate_words, 
                    args=(lyrics_data, song_name, song_id, update_translations)
                ).start()
    else:
        tree.insert("", "end", values=("0:00", "(No lyrics)", ""))
        translated_song_name = None
    
    adjust_column_widths()

# Function to update the Treeview with translated lyrics
def update_translations(translated_lyrics):
    for item in tree.get_children():
        item_data = tree.item(item)
        start_time = item_data['values'][0]
        original_lyrics = item_data['values'][1]
        for lyric in translated_lyrics:
            if ms_to_min_sec(lyric['startTimeMs']) == start_time and lyric['words'] == original_lyrics:
                tree.set(item, column="Translated Lyrics", value=lyric['translated'])
                break
    if tree.get_children():
        first_item = tree.get_children()[0]
        tree.set(first_item, column="Translated Lyrics", value=translated_lyrics[0]['translated'])
    adjust_column_widths()

# Function to find the longest line length in original and translated lyrics
def find_longest_line_lengths():
    max_original_length = 0
    max_translated_length = 0
    line_count = 0

    for item in tree.get_children():
        line_count += 1
        original_length = len(tree.item(item)['values'][1])
        translated_length = len(tree.item(item)['values'][2])
        if original_length > max_original_length:
            max_original_length = original_length
        if translated_length > max_translated_length:
            max_translated_length = translated_length

    return max_original_length, max_translated_length, line_count

# Function to adjust the column widths based on the content
def adjust_column_widths():
    min_time_width = 50  # Minimum width for the "Time" column
    max_original_length, max_translated_length, line_count = find_longest_line_lengths()

    root.update_idletasks()
    width = tree.winfo_reqwidth()

    orig_length=max_original_length*10
    trans_length = max_translated_length * 10

    if language=="ja":
        orig_length=max_original_length*23
    if language=="ru":
        orig_length=max_original_length*18
        trans_length=max_translated_length*19







    width = min_time_width + orig_length + trans_length

    # Get the required height for the treeview
    tree_height = tree.winfo_reqheight()

    # Add the height of the current time label and some padding
    height = line_count * 17 + 100

    #print(f"Width: {width}, Height: {height}")
    #print(f"Max Original Length: {max_original_length}, Max Translated Length: {max_translated_length}")

    # Update the window size
    # get current width
    current_width = root.winfo_width()

    tree.column("Time", width=60, minwidth=50, stretch=False)
    tree.column("Original Lyrics", width=200, minwidth=100)
    tree.column("Translated Lyrics", width=200, minwidth=100)
    root.geometry(f"{current_width}x{height}") # there's no need to updated the window size esp if the user has updated it themselves.

# Create main application window

root = tk.Tk()

root.title("Spotify Lyrics Translator")

# Apply a theme to the Tkinter application
style = ttk.Style(root)
style.theme_use("default")  # Use a base theme that can be customized

# Customize Treeview styles with green theme
style.configure("Treeview.Heading", font=('Helvetica', 12, 'bold'), background='#4CAF50', foreground='white')
style.configure("Treeview", font=('Arial', 14), rowheight=40, background='#E8F5E9', foreground='black', fieldbackground='#E8F5E9')
sv_ttk.set_theme("dark")
style.configure("Treeview",rowheight=25)

style.map('Treeview', background=[('selected', '#81C784')], foreground=[('selected', 'white')])

# Force update of the Treeview style
root.update_idletasks()

# Current time label
current_time_label = tk.Label(root, text="Current Time: 00:00", font=('Helvetica', 12, 'bold'), bg='#388E3C', fg='#fff', padx=10, pady=5)
current_time_label.pack(side=tk.TOP, fill=tk.X)

# Create a frame to hold the Treeview and Scrollbar
frame = ttk.Frame(root, padding="10 10 10 10")
frame.pack(fill=tk.BOTH, expand=True)

# Create and pack the treeview widget
style.configure("Treeview.Heading", foreground="lightgreen", font=('Helvetica', 14, 'bold'))

tree = ttk.Treeview(frame, columns=("Time", "Original Lyrics", "Translated Lyrics"), show="headings", style="Treeview")
tree.heading("Time", text="  Time", anchor='w')
tree.heading(f"Original Lyrics", text=f"  Original Lyrics", anchor='w')
tree.heading("Translated Lyrics", text="  Translated Lyrics", anchor='w')
tree.column("Time", width=200, minwidth=200, anchor='w')
tree.column(f"Original Lyrics", width=250, anchor='w')
tree.column("Translated Lyrics", width=250, anchor='w')

# Update the column heading style to green
tree.tag_configure('heading', foreground='#4CAF50')

# Create the Scrollbar
scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=scrollbar.set)
tree.pack(side='left', fill=tk.BOTH, expand=True)
scrollbar.pack(side='right', fill='y')

# Start the update in a non-blocking manner
root.after(500, update_display)  # Initial call to start the loop with reduced frequency

def inspect_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            cache = pickle.load(f)
            print("\n=== CACHE CONTENTS ===")
            print("showing only first 5 entries")
            for song_id, translations in cache.items():
                print(f"\nSong ID: {song_id}")
                for entry in translations[:5]:  # Show first 5 entries
                    print(f"Time: {ms_to_min_sec(entry['startTimeMs'])}")
                    print(f"Original: {entry['words']}")
                    print(f"Translated: {entry['translated']}\n")
                print("...")
    else:
        print("No cache file found")

# Add new function for streaming translation
def stream_translate_line(line, song_name, song_id):
    global translated_song_name
    
    translator = GoogleTranslator(source='auto', target='en')
    
    # Translate song name if not already translated
    if translated_song_name is None:
        translated_song_name = translator.translate(song_name)
        root.title(f"{song_name}: {translated_song_name}")
    
    result = translate_line(translator, line)
    
    # Update UI immediately with the single translated line
    for item in tree.get_children():
        item_data = tree.item(item)
        start_time = item_data['values'][0]
        original_lyrics = item_data['values'][1]
        if ms_to_min_sec(result['startTimeMs']) == start_time and result['words'] == original_lyrics:
            tree.set(item, column="Translated Lyrics", value=result['translated'])
            break
    
    # Update cache if enabled
    if USE_CACHE:
        if song_id not in lyrics_cache:
            lyrics_cache[song_id] = []
        lyrics_cache[song_id].append(result)
        if len(lyrics_cache) > MAX_CACHE_SIZE:
            lyrics_cache.pop(next(iter(lyrics_cache)))
        save_cache()

# Start the application
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg == "inspect":
                inspect_cache()
                sys.exit()
            elif arg == "no-cache":
                USE_CACHE = False
                debug_print("Cache disabled")
            elif arg == "debug":
                DEBUG_MODE = True
                debug_print("Debug mode enabled")
            elif arg == "threading":
                USE_THREADING = True
                debug_print("Multi-threaded mode enabled")
            elif arg == "batch":
                streaming_mode = False
                debug_print("Batch mode enabled")
    root.mainloop()


