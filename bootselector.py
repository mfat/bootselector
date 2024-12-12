#!/usr/bin/env python3
import os
import sys
import subprocess
import re
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio
import webbrowser



VERSION = "1.0.0"
APP_NAME = "Boot Selector"
AUTHOR = "mFat"
WEBSITE = "https://github.com/mfat/bootselector"
LICENSE = "GPL v3"

GRUB_ENV_FILE = '/boot/grub/grubenv'
GRUB_CONFIG = '/boot/grub/grub.cfg'
GRUB_DEFAULT_FILE = '/etc/default/grub'
GRUB_EDITENV = '/usr/bin/grub-editenv'
GRUB_REBOOT = '/usr/sbin/grub-reboot'
UPDATE_GRUB = '/usr/sbin/update-grub'

def check_root():
    if os.geteuid() != 0:
        try:
            cmd = [
                'pkexec',
                'env',
                f'DISPLAY={os.environ.get("DISPLAY", "")}',
                f'XAUTHORITY={os.environ.get("XAUTHORITY", "")}',
                f'XDG_RUNTIME_DIR={os.environ.get("XDG_RUNTIME_DIR", "")}',
                f'WAYLAND_DISPLAY={os.environ.get("WAYLAND_DISPLAY", "")}',
                f'DBUS_SESSION_BUS_ADDRESS={os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")}',
                f'XDG_SESSION_TYPE={os.environ.get("XDG_SESSION_TYPE", "")}',
                f'HOME={os.environ.get("HOME", "")}',
                f'USER={os.environ.get("USER", "")}',
                sys.executable,
                os.path.abspath(sys.argv[0])
            ]
            subprocess.run(cmd)
            sys.exit(0)
        except Exception as e:
            print(f"Error obtaining root privileges: {e}")
            sys.exit(1)

def check_dependencies():
    missing = []
    for cmd in [GRUB_EDITENV, GRUB_REBOOT, UPDATE_GRUB]:
        if not os.path.exists(cmd):
            missing.append(os.path.basename(cmd))
    
    if missing:
        error = f"Missing required commands: {', '.join(missing)}\n"
        error += "Please install the grub2-common package"
        return False, error
    return True, ""

def clean_title(title):
    match = re.search(r"'([^']+)'|\"([^\"]+)\"", title)
    if match:
        return match.group(1) or match.group(2)
    return title.strip()

class BootSelector(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_default_size(600, 400)
        
        # Setup header bar
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(APP_NAME)
        self.set_titlebar(header)
        
        # Menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.MENU))
        
        # Menu
        menu = Gio.Menu()
        menu.append("About", "app.about")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
        
        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_clicked)
        self.add_action(about_action)
        
        # Check dependencies
        deps_ok, error = check_dependencies()
        if not deps_ok:
            self.show_error(error)
            sys.exit(1)
        
        self.entries = []
        self.submenu_states = {1: True}
        
        # Main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_border_width(10)
        self.add(vbox)

        # Tree view
        self.store = Gtk.ListStore(str, str, bool, object)  # display title, entry_id, is_submenu, entry_info
        self.tree_view = Gtk.TreeView(model=self.store)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Boot Entry", renderer, text=0)
        self.tree_view.append_column(column)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.tree_view)
        vbox.pack_start(scrolled, True, True, 0)
        
        # Buttons
        button_box = Gtk.Box(spacing=6)
        
        set_default_btn = Gtk.Button(label="Set as Default")
        set_default_btn.connect("clicked", self.on_set_default)
        button_box.pack_start(set_default_btn, True, True, 0)
        
        reboot_btn = Gtk.Button(label="Reboot into Selected")
        reboot_btn.connect("clicked", self.on_reboot_clicked)
        button_box.pack_start(reboot_btn, True, True, 0)
        
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", self.refresh_entries)
        button_box.pack_start(refresh_btn, True, True, 0)
        
        vbox.pack_start(button_box, False, False, 0)
        
        self.tree_view.connect("button-press-event", self.on_tree_click)
        self.refresh_entries()

    def parse_entries(self):
        entries = []
        submenu_entries = []
        in_submenu = False
        brace_count = 0

        try:
            with open(GRUB_CONFIG, 'r') as f:
                content = f.read()

            for line in content.split('\n'):
                line = line.strip()
                
                if '{' in line:
                    brace_count += 1
                if '}' in line:
                    brace_count -= 1
                    if brace_count == 0 and in_submenu:
                        in_submenu = False

                if line.startswith('menuentry '):
                    title = clean_title(line)
                    if in_submenu:
                        submenu_entries.append({
                            'title': title,
                            'id': f'1>{len(submenu_entries)}',
                            'in_submenu': True,
                            'parent_index': 1
                        })
                    else:
                        entries.append({
                            'title': title,
                            'id': str(len(entries)),
                            'in_submenu': False
                        })
                elif line.startswith('submenu '):
                    title = clean_title(line)
                    entries.append({
                        'title': title,
                        'id': '1',
                        'is_submenu': True,
                        'expanded': self.submenu_states.get(1, True)
                    })
                    in_submenu = True
                    brace_count = 1

            # Insert submenu entries after the submenu header
            if submenu_entries:
                submenu_index = next(i for i, e in enumerate(entries) if e.get('is_submenu'))
                entries[submenu_index+1:submenu_index+1] = submenu_entries

        except Exception as e:
            self.show_error(f"Error reading GRUB configuration: {e}")
            return []

        return entries

    def refresh_entries(self, widget=None):
        self.entries = self.parse_entries()
        self.store.clear()
        current_default = self.get_current_default()
        
        for entry in self.entries:
            show = True
            if entry.get('in_submenu'):
                show = self.submenu_states.get(1, True)
                
            if show:
                title = entry['title']
                if entry.get('is_submenu'):
                    arrow = "▼ " if entry.get('expanded', True) else "▶ "
                    title = arrow + clean_title(title)
                elif entry.get('in_submenu'):
                    title = "    " + clean_title(title)
                else:
                    title = clean_title(title)
                    
                if entry['id'] == current_default:
                    title = f"[DEFAULT] {title}"
                    
                self.store.append([title, entry['id'], entry.get('is_submenu', False), entry])

    def get_current_default(self):
        try:
            with open(GRUB_DEFAULT_FILE, 'r') as f:
                for line in f:
                    if line.startswith('GRUB_DEFAULT='):
                        return line.split('=')[1].strip().strip('"\'')
        except Exception:
            return "0"
        return "0"

    def set_default_entry(self, entry_id):
        try:
            lines = []
            try:
                with open(GRUB_DEFAULT_FILE, 'r') as f:
                    lines = f.readlines()
            except FileNotFoundError:
                pass

            default_exists = False
            for i, line in enumerate(lines):
                if line.startswith('GRUB_DEFAULT='):
                    lines[i] = f'GRUB_DEFAULT="{entry_id}"\n'
                    default_exists = True
                    break

            if not default_exists:
                lines.insert(0, f'GRUB_DEFAULT="{entry_id}"\n')

            with open(GRUB_DEFAULT_FILE, 'w') as f:
                f.writelines(lines)

            subprocess.run([UPDATE_GRUB], check=True)
            self.show_message("Default boot entry updated successfully!")
            self.refresh_entries()
            
        except Exception as e:
            self.show_error(f"Error setting default entry: {e}")

    def on_tree_click(self, widget, event):
        if event.button == 1:
            path = self.tree_view.get_path_at_pos(int(event.x), int(event.y))
            if path:
                iter_ = self.store.get_iter(path[0])
                is_submenu = self.store.get_value(iter_, 2)
                if is_submenu:
                    self.submenu_states[1] = not self.submenu_states.get(1, True)
                    self.refresh_entries()
                    return True

    def on_reboot_clicked(self, widget):
        selection = self.tree_view.get_selection()
        model, iter_ = selection.get_selected()
        if not iter_:
            self.show_error("Please select a boot entry")
            return
            
        entry = model.get_value(iter_, 3)
        if entry.get('is_submenu'):
            self.show_error("Cannot reboot into a submenu")
            return
            
        entry_id = model.get_value(iter_, 1)
        title = clean_title(entry['title'])
        
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Confirm Reboot"
        )
        dialog.format_secondary_text(f"Are you sure you want to reboot into:\n{title}")
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            try:
                subprocess.run([GRUB_REBOOT, entry_id], check=True)
                subprocess.run(['reboot'], check=True)
            except subprocess.CalledProcessError as e:
                self.show_error(f"Error setting reboot entry: {e}")

    def on_set_default(self, widget):
        selection = self.tree_view.get_selection()
        model, iter_ = selection.get_selected()
        if iter_:
            entry = model.get_value(iter_, 3)
            if entry.get('is_submenu'):
                self.show_error("Cannot set a submenu as default")
                return
            entry_id = model.get_value(iter_, 1)
            self.set_default_entry(entry_id)

    def on_about_clicked(self, action, param):
        window = self.get_active_window()
        dialog = Gtk.AboutDialog(transient_for=window)
        dialog.set_modal(True)
        
        icon_theme = Gtk.IconTheme.get_default()
        dialog.set_logo(icon_theme.load_icon("open-menu-symbolic", 64, 0))
        
        dialog.set_program_name(APP_NAME)
        dialog.set_version(VERSION)
        dialog.set_copyright(f" 2024 {AUTHOR}")
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.set_website(WEBSITE)
        dialog.set_website_label("Project Website")
        dialog.set_authors([AUTHOR])
        
        # Connect to activate-link signal to handle URL opening
        dialog.connect("activate-link", self._on_activate_link)
        
        dialog.run()
        dialog.destroy()

    def _on_activate_link(self, dialog, uri):
        try:
            # Get the current user's real username (even when running as root)
            real_user = os.environ.get('SUDO_USER') or os.environ.get('USER')
            if real_user == 'root':
                print("Warning: Cannot open browser as root user")
                return True
                
            # If running as root but SUDO_USER exists, run browser as the real user
            if os.geteuid() == 0 and real_user and real_user != 'root':
                cmd = ['sudo', '-u', real_user, 'xdg-open', uri]
            else:
                cmd = ['xdg-open', uri]
                
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Error opening URL: {e}")
        return True

    def show_error(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()

    def show_message(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()

class BootSelectorApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.mfat.bootselector")
        self.create_actions()

    def create_actions(self):
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_about_clicked)
        self.add_action(about_action)

    def on_about_clicked(self, action, param):
        window = self.get_active_window()
        dialog = Gtk.AboutDialog(transient_for=window)
        dialog.set_modal(True)
        
        icon_theme = Gtk.IconTheme.get_default()
        dialog.set_logo(icon_theme.load_icon("open-menu-symbolic", 64, 0))
        
        dialog.set_program_name(APP_NAME)
        dialog.set_version(VERSION)
        dialog.set_copyright(f" 2024 {AUTHOR}")
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.set_website(WEBSITE)
        dialog.set_website_label("Project Website")
        dialog.set_authors([AUTHOR])
        
        # Connect to activate-link signal to handle URL opening
        dialog.connect("activate-link", self._on_activate_link)
        
        dialog.run()
        dialog.destroy()

    def _on_activate_link(self, dialog, uri):
        try:
            # Get the current user's real username (even when running as root)
            real_user = os.environ.get('SUDO_USER') or os.environ.get('USER')
            if real_user == 'root':
                print("Warning: Cannot open browser as root user")
                return True
                
            # If running as root but SUDO_USER exists, run browser as the real user
            if os.geteuid() == 0 and real_user and real_user != 'root':
                cmd = ['sudo', '-u', real_user, 'xdg-open', uri]
            else:
                cmd = ['xdg-open', uri]
                
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Error opening URL: {e}")
        return True

    def do_activate(self):
        window = BootSelector(application=self)
        window.show_all()

def main():
    check_root()
    app = BootSelectorApp()
    app.run(sys.argv)

if __name__ == "__main__":
    main()