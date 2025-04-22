#!/usr/bin/env python3
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog
import threading
import argparse
import json
import time
from functools import lru_cache
import re
import subprocess
from pathlib import Path

# Configuration
CONFIG_DIR = os.path.expanduser("~/.file-tree-viewer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Default configuration
DEFAULT_CONFIG = {
    "ignored_patterns": ["__pycache__", "*.pyc", "*.pyo", "*.jpg", "*.png", "*.gif", "*.pdf"],
    "recent_directories": [],
    "window_size": [800, 600]
}

# Ensure config directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)

# Load or create configuration
def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        else:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            return DEFAULT_CONFIG
    except Exception as e:
        print(f"Error loading config: {e}")
        return DEFAULT_CONFIG

# Save configuration
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

# Cache for file contents to improve performance
@lru_cache(maxsize=100)
def get_file_content(file_path):
    """Get the full content of a file, with proper error handling"""
    try:
        # Check if file exists and is readable
        if not os.path.isfile(file_path) or not os.access(file_path, os.R_OK):
            return "(Файл недоступен для чтения)"
        
        # Skip binary files quickly by checking first few bytes
        with open(file_path, 'rb') as f:
            first_bytes = f.read(8192)
            if b'\x00' in first_bytes:
                return "(Бинарный файл, содержимое не отображается)"
        
        # Read text content (full file)
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return content
    except UnicodeDecodeError:
        return "(Бинарный файл, содержимое не отображается)"
    except Exception as e:
        return f"(Ошибка чтения файла: {str(e)})"

def should_ignore(path, ignore_patterns):
    """Check if a file/directory should be ignored based on patterns"""
    filename = os.path.basename(path)
    
    for pattern in ignore_patterns:
        # Direct match
        if pattern == filename:
            return True
        # Path contains pattern
        if pattern in path:
            return True
        # Wildcard extension match (*.ext)
        if pattern.startswith('*.') and filename.endswith(pattern[1:]):
            return True
        # Regex match for more complex patterns
        try:
            if re.match(f"^{pattern.replace('*', '.*')}$", filename):
                return True
        except:
            pass
    return False

class FileTreeViewer(tk.Tk):
    def __init__(self, initial_dir=None):
        super().__init__()
        
        # Load configuration
        self.config_data = load_config()
        
        # Setup main window
        self.title("File Tree Viewer")
        self.geometry(f"{self.config_data['window_size'][0]}x{self.config_data['window_size'][1]}")
        
        # Configure Tkinter to show hidden files
        try:
            # Call a dummy dialog with an impossible option to initialize the file dialog
            # without really getting a dialog window; this will throw a TclError
            try:
                self.tk.call('tk_getOpenFile', '-foobarbaz')
            except tk.TclError:
                pass
            
            # Now set the magic variables to show hidden files
            self.tk.call('set', '::tk::dialog::file::showHiddenBtn', '1')
            self.tk.call('set', '::tk::dialog::file::showHiddenVar', '1')
        except Exception as e:
            print(f"Warning: Could not configure Tkinter to show hidden files: {e}")
        
        # Set window icon if available
        try:
            self.iconbitmap('file-tree-icon.ico')  # You can create and include an icon file
        except:
            pass
        
        # Variables
        self.current_dir = tk.StringVar(value=initial_dir or os.getcwd())
        self.status_text = tk.StringVar(value="Ready")
        self.is_loading = False
        self.tree_items = {}
        self.checked_items = set()
        
        # Create main frame with padding
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create toolbar
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        # Directory selection
        ttk.Label(toolbar, text="Directory:").pack(side=tk.LEFT, padx=(0, 5))
        dir_entry = ttk.Entry(toolbar, textvariable=self.current_dir, width=40)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        browse_btn = ttk.Button(toolbar, text="Browse...", command=self.browse_directory)
        browse_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        refresh_btn = ttk.Button(toolbar, text="Refresh", command=self.refresh_tree)
        refresh_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Second toolbar row
        toolbar2 = ttk.Frame(main_frame)
        toolbar2.pack(fill=tk.X, pady=(0, 10))
        
        # Check/uncheck buttons
        check_all_btn = ttk.Button(toolbar2, text="Check All", command=self.check_all)
        check_all_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        uncheck_all_btn = ttk.Button(toolbar2, text="Uncheck All", command=self.uncheck_all)
        uncheck_all_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Generate output button
        generate_btn = ttk.Button(toolbar2, text="Generate & Copy Output", command=self.generate_output)
        generate_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Frame for tree with scrollbar
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Set up tree style for checkboxes
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=25)  # Increase row height for checkboxes
        
        # Tree with checkboxes
        self.tree = ttk.Treeview(tree_frame, selectmode="browse")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Add scrollbar to tree
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        # Configure tree columns - Add proper checkbox column
        self.tree["columns"] = ("checked",)
        self.tree.column("#0", width=400, minwidth=200)
        self.tree.column("checked", width=50, anchor=tk.CENTER)
        self.tree.heading("#0", text="Files and Directories")
        self.tree.heading("checked", text="✓")
        
        # Bind tree events
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Button-1>", self.on_tree_click)
        
        # Status bar
        status_bar = ttk.Label(main_frame, textvariable=self.status_text, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        
        # Populate recent directories menu
        self.create_menu()
        
        # Load the initial directory
        self.refresh_tree()
        
        # Add directory to recent list
        if initial_dir and os.path.isdir(initial_dir):
            self.add_recent_directory(initial_dir)
            
        # Bind window close event
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # UI for showing copy notification
        self.copy_notification = None
    
    def create_menu(self):
        """Create application menu"""
        menu_bar = tk.Menu(self)
        
        # File menu
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Open Directory...", command=self.browse_directory)
        
        # Recent directories submenu
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        for directory in self.config_data.get("recent_directories", []):
            self.recent_menu.add_command(
                label=directory, 
                command=lambda d=directory: self.load_directory(d)
            )
        
        file_menu.add_cascade(label="Recent Directories", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        
        # Settings menu
        settings_menu = tk.Menu(menu_bar, tearoff=0)
        settings_menu.add_command(label="Edit Ignored Patterns", command=self.edit_ignored_patterns)
        
        # Help menu
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        
        # Add menus to menu bar
        menu_bar.add_cascade(label="File", menu=file_menu)
        menu_bar.add_cascade(label="Settings", menu=settings_menu)
        menu_bar.add_cascade(label="Help", menu=help_menu)
        
        self.config(menu=menu_bar)
    
    def update_recent_menu(self):
        """Update the recent directories menu"""
        self.recent_menu.delete(0, tk.END)
        for directory in self.config_data.get("recent_directories", []):
            self.recent_menu.add_command(
                label=directory, 
                command=lambda d=directory: self.load_directory(d)
            )
    
    def add_recent_directory(self, directory):
        """Add a directory to recent list"""
        recent = self.config_data.get("recent_directories", [])
        
        # Remove if already exists
        if directory in recent:
            recent.remove(directory)
        
        # Add to beginning
        recent.insert(0, directory)
        
        # Keep only last 10
        self.config_data["recent_directories"] = recent[:10]
        
        # Save config
        save_config(self.config_data)
        
        # Update menu
        self.update_recent_menu()
    
    def browse_directory(self):
        """Open directory browser dialog"""
        directory = filedialog.askdirectory(initialdir=self.current_dir.get())
        if directory:
            self.load_directory(directory)
    
    def load_directory(self, directory):
        """Load a directory into the tree"""
        if os.path.isdir(directory):
            self.current_dir.set(directory)
            self.add_recent_directory(directory)
            self.refresh_tree()
    
    def refresh_tree(self):
        """Refresh the file tree"""
        # Skip if already loading
        if self.is_loading:
            return
        
        self.is_loading = True
        self.status_text.set("Loading directory structure...")
        self.update_idletasks()
        
        # Clear existing tree
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.tree_items = {}
        self.checked_items = set()
        
        # Start loading thread
        directory = self.current_dir.get()
        
        threading.Thread(target=self.load_tree_thread, args=(directory,), daemon=True).start()
    
    def load_tree_thread(self, directory):
        """Background thread to load tree structure"""
        try:
            # Get the ignored patterns from config
            ignored_patterns = self.config_data.get("ignored_patterns", DEFAULT_CONFIG["ignored_patterns"])
            
            # We need to use after to update the status from the main thread
            self.after(0, lambda: self.status_text.set("Loading directory structure..."))
            
            # Populate tree
            self.populate_tree("", directory, ignored_patterns)
            
            # Update status when done
            self.after(0, lambda: self.status_text.set(f"Loaded directory: {directory}"))
        except Exception as e:
            # Use after to update UI from the main thread
            self.after(0, lambda: self.status_text.set(f"Error loading directory: {str(e)}"))
        finally:
            # Update loading flag in the main thread
            self.after(0, lambda: setattr(self, 'is_loading', False))
    
    def populate_tree(self, parent, directory, ignored_patterns):
        """Recursively populate the tree including all files"""
        try:
            # Function to get all files including hidden ones
            def get_all_files(path):
                try:
                    all_items = []
                    for item in os.listdir(path):
                        item_path = os.path.join(path, item)
                        all_items.append(item_path)
                    return all_items
                except PermissionError:
                    return []
                except Exception as e:
                    print(f"Error scanning {path}: {e}")
                    return []
            
            # Get all items
            all_items = get_all_files(directory)
            
            # If no items could be retrieved, show error
            if not all_items:
                error_id = f"{parent}_error_{hash(directory)}"
                self.tree.insert(parent, "end", error_id, text=f"Error: Permission denied or empty directory")
                return
            
            # Split into directories and files
            dirs = []
            files = []
            
            for item_path in all_items:
                item_name = os.path.basename(item_path)
                    
                # Skip . and .. entries
                if item_name in ['.', '..']:
                    continue
                    
                # Skip ignored items
                if should_ignore(item_path, ignored_patterns):
                    continue
                    
                if os.path.isdir(item_path):
                    dirs.append((item_name, item_path))
                else:
                    files.append((item_name, item_path))
            
            # Sort each group alphabetically
            dirs.sort(key=lambda x: x[0].lower())
            files.sort(key=lambda x: x[0].lower())
            
            # Process directories first, then files
            for item_name, item_path in dirs + files:
                # Generate item ID (ensure uniqueness even with special chars)
                unique_id = f"{parent}_{str(hash(item_path))}"
                
                if os.path.isdir(item_path):
                    # Add directory item
                    if item_name == "node_modules":
                        # Special handling for node_modules
                        tree_id = self.tree.insert(
                            parent, "end", unique_id, 
                            text=f"{item_name} (skipped content)",
                            values=("⬜", "directory", item_path)
                        )
                        self.tree_items[tree_id] = {
                            "path": item_path, 
                            "type": "directory",
                            "is_ignored": True
                        }
                    else:
                        # Normal directory
                        tree_id = self.tree.insert(
                            parent, "end", unique_id, 
                            text=item_name,
                            values=("⬜", "directory", item_path)
                        )
                        self.tree_items[tree_id] = {
                            "path": item_path, 
                            "type": "directory",
                            "is_ignored": False
                        }
                        
                        # Recursively populate subdirectory
                        self.populate_tree(tree_id, item_path, ignored_patterns)
                else:
                    # Add file item
                    tree_id = self.tree.insert(
                        parent, "end", unique_id, 
                        text=item_name,
                        values=("⬜", "file", item_path)
                    )
                    self.tree_items[tree_id] = {
                        "path": item_path, 
                        "type": "file",
                        "is_ignored": False
                    }
        except Exception as e:
            # Handle errors
            error_id = f"{parent}_error_{hash(directory)}"
            self.tree.insert(parent, "end", error_id, text=f"Error: {str(e)}")
    
    def on_tree_double_click(self, event):
        """Handle double click on tree item"""
        # Get clicked item
        item_id = self.tree.identify("item", event.x, event.y)
        if not item_id:
            return
            
        # Get item info
        item_info = self.tree_items.get(item_id)
        if not item_info:
            return
            
        # If it's a file, toggle its checked state
        if item_info["type"] == "file" and not item_info["is_ignored"]:
            self.toggle_check(item_id)
    
    def on_tree_click(self, event):
        """Handle click on tree item (for checkbox)"""
        # Get clicked region
        region = self.tree.identify("region", event.x, event.y)
        
        # If clicked on the checkbox column
        if region == "cell" and self.tree.identify_column(event.x) == "#1":
            item_id = self.tree.identify("item", event.x, event.y)
            if item_id:
                self.toggle_check(item_id)
                return "break"  # Prevent default handling
    
    def toggle_check(self, item_id):
        """Toggle checkbox for an item"""
        item_info = self.tree_items.get(item_id)
        if not item_info or item_info["is_ignored"]:
            return
            
        current_value = self.tree.item(item_id, "values")[0]
        new_value = "✅" if current_value == "⬜" else "⬜"
        
        # Update tree item
        values = list(self.tree.item(item_id, "values"))
        values[0] = new_value
        self.tree.item(item_id, values=values)
        
        # Update checked items set
        if new_value == "✅":
            self.checked_items.add(item_id)
        else:
            self.checked_items.discard(item_id)
        
        # If it's a directory, update all children
        if item_info["type"] == "directory":
            self.update_children_check(item_id, new_value == "✅")
    
    def update_children_check(self, parent_id, checked):
        """Update check state of all children"""
        for child_id in self.tree.get_children(parent_id):
            item_info = self.tree_items.get(child_id)
            if item_info and not item_info["is_ignored"]:
                # Update tree item
                values = list(self.tree.item(child_id, "values"))
                values[0] = "✅" if checked else "⬜"
                self.tree.item(child_id, values=values)
                
                # Update checked items set
                if checked:
                    self.checked_items.add(child_id)
                else:
                    self.checked_items.discard(child_id)
                
                # Recursively update children if it's a directory
                if item_info["type"] == "directory":
                    self.update_children_check(child_id, checked)
    
    def check_all(self):
        """Check all items in the tree"""
        for item_id in self.tree.get_children():
            item_info = self.tree_items.get(item_id)
            if item_info and not item_info["is_ignored"]:
                values = list(self.tree.item(item_id, "values"))
                values[0] = "✅"
                self.tree.item(item_id, values=values)
                self.checked_items.add(item_id)
                
                if item_info["type"] == "directory":
                    self.update_children_check(item_id, True)
    
    def uncheck_all(self):
        """Uncheck all items in the tree"""
        for item_id in self.tree.get_children():
            item_info = self.tree_items.get(item_id)
            if item_info and not item_info["is_ignored"]:
                values = list(self.tree.item(item_id, "values"))
                values[0] = "⬜"
                self.tree.item(item_id, values=values)
                self.checked_items.discard(item_id)
                
                if item_info["type"] == "directory":
                    self.update_children_check(item_id, False)
    
    def show_copy_notification(self):
        """Show a notification that content was copied to clipboard"""
        # Remove previous notification if exists
        if self.copy_notification:
            self.copy_notification.destroy()
        
        # Create new notification
        self.copy_notification = tk.Toplevel(self)
        self.copy_notification.overrideredirect(True)
        
        # Position near the mouse
        x = self.winfo_pointerx() + 10
        y = self.winfo_pointery() + 10
        
        # Create notification content
        frame = ttk.Frame(self.copy_notification, padding=10, relief="raised", borderwidth=1)
        frame.pack(fill=tk.BOTH, expand=True)
        
        label = ttk.Label(frame, text="Output copied to clipboard", font=("Arial", 12))
        label.pack(padx=10, pady=10)
        
        # Position notification
        self.copy_notification.geometry(f"+{x}+{y}")
        
        # Fade after 2 seconds
        self.after(2000, self.hide_copy_notification)
    
    def hide_copy_notification(self):
        """Hide copy notification"""
        if self.copy_notification:
            self.copy_notification.destroy()
            self.copy_notification = None
    
    def generate_output(self):
        """Generate text output based on checked items"""
        # Start with root directory
        directory = self.current_dir.get()
        output = f"ContentTree: {directory}\n"
        
        # Process top-level items
        for item_id in self.tree.get_children():
            output += self.process_item_for_output(item_id, "")
        
        # Save to clipboard
        self.clipboard_clear()
        self.clipboard_append(output)
        
        # Show status and notification
        self.status_text.set("Output generated and copied to clipboard")
        self.show_copy_notification()
    
    def process_item_for_output(self, item_id, prefix):
        """Process a tree item for output generation"""
        item_info = self.tree_items.get(item_id)
        if not item_info:
            return ""
            
        # Get item properties
        name = os.path.basename(item_info["path"])
        is_checked = item_id in self.checked_items
        is_last = self.tree.next(item_id) == ""
        item_prefix = prefix + ("└── " if is_last else "├── ")
        child_prefix = prefix + ("    " if is_last else "│   ")
        
        output = item_prefix + name + "\n"
        
        # For files, include content if checked
        if item_info["type"] == "file":
            if is_checked:
                content = get_file_content(item_info["path"])
                # Format content with prefix
                formatted_content = '\n'.join([child_prefix + line for line in content.split('\n')])
                output += formatted_content + "\n"
                output += child_prefix + "-" * 40 + "\n"
            else:
                output += child_prefix + "<-- Content skipped -->\n"
        
        # For directories, process children if not ignored
        elif item_info["type"] == "directory" and not item_info["is_ignored"]:
            if item_info["path"].endswith("node_modules"):
                output += child_prefix + "<-- node_modules (skipped) -->\n"
            else:
                # Process children
                children = self.tree.get_children(item_id)
                if not children:
                    # Empty directory
                    output += child_prefix + "(empty directory)\n"
                else:
                    # Process each child
                    for i, child_id in enumerate(children):
                        is_last_child = (i == len(children) - 1)
                        child_info = self.tree_items.get(child_id)
                        
                        if child_info:
                            if child_id in self.checked_items or child_info["type"] == "directory":
                                output += self.process_item_for_output(child_id, child_prefix)
                            else:
                                # Add simple entry for unchecked files
                                child_name = os.path.basename(child_info["path"])
                                child_item_prefix = child_prefix + ("└── " if is_last_child else "├── ")
                                child_content_prefix = child_prefix + ("    " if is_last_child else "│   ")
                                output += child_item_prefix + child_name + "\n"
                                output += child_content_prefix + "<-- Content skipped -->\n"
        
        return output
    
    def edit_ignored_patterns(self):
        """Edit ignored patterns dialog"""
        dialog = tk.Toplevel(self)
        dialog.title("Edit Ignored Patterns")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()
        
        # Description label
        ttk.Label(dialog, text="Enter patterns to ignore (one per line):").pack(pady=(10, 5))
        ttk.Label(dialog, text="Examples: *.txt, node_modules").pack(pady=(0, 10))
        
        # Text area
        text = tk.Text(dialog, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Scrollbar for text
        scrollbar = ttk.Scrollbar(text, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)
        
        # Populate with current patterns
        patterns = self.config_data.get("ignored_patterns", DEFAULT_CONFIG["ignored_patterns"])
        text.insert(tk.END, "\n".join(patterns))
        
        def save_patterns():
            # Get patterns from text
            patterns_text = text.get(1.0, tk.END).strip()
            new_patterns = [p.strip() for p in patterns_text.split("\n") if p.strip()]
            
            # Update config
            self.config_data["ignored_patterns"] = new_patterns
            save_config(self.config_data)
            
            # Close dialog
            dialog.destroy()
            
            # Refresh tree
            self.refresh_tree()
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="Save", command=save_patterns).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def show_about(self):
        """Show about dialog"""
        about_text = """File Tree Viewer

Графическая утилита для просмотра структуры директорий и содержимого файлов.

Возможности:
• Просмотр дерева файлов и директорий (включая скрытые)
• Выбор файлов для включения в вывод
• Игнорирование указанных шаблонов файлов
• Копирование результата в буфер обмена
• Сортировка (директории сначала, затем файлы)
"""
        
        dialog = tk.Toplevel(self)
        dialog.title("О программе File Tree Viewer")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()
        
        text = tk.Text(dialog, wrap=tk.WORD)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text.insert(tk.END, about_text)
        text.config(state=tk.DISABLED)
        
        ttk.Button(dialog, text="Закрыть", command=dialog.destroy).pack(pady=10)
    
    def on_close(self):
        """Handle window close event"""
        # Save window size to config
        self.config_data["window_size"] = [self.winfo_width(), self.winfo_height()]
        save_config(self.config_data)
        
        # Destroy window
        self.destroy()

def main():
    parser = argparse.ArgumentParser(description='File Tree Viewer')
    parser.add_argument('directory', nargs='?', help='Directory to open')
    
    args = parser.parse_args()
    
    # Get directory from command line or use current directory
    directory = os.path.abspath(args.directory if args.directory else os.getcwd())
    
    # Start application
    app = FileTreeViewer(directory)
    app.mainloop()

if __name__ == "__main__":
    main()