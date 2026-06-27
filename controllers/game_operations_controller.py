# WHY: Single Responsibility Principle - Exclusively handles user-driven mutations 
# to the game library (Batch Edits, Deletions, Merges, Meta Purging).
import os
import logging
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox

from backend.library import LibraryManager
from ViGaVault_utils import build_scanner_config, get_db_path, translator, get_image_path, get_video_path, normalize_genre
from dialogs import ConflictDialog

class GameOperationsController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window



    def update_game_data(self, folder_name, new_data):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game_obj = manager.games.get(folder_name)
        if not game_obj: return

        old_title = game_obj.data.get('Clean_Title', '')
        old_date = game_obj.data.get('Original_Release_Date', '')

        for key, value in new_data.items(): game_obj.data[key] = value
        game_obj.update_media_filenames(old_title, old_date)
        
        while True:
            try:
                manager.save_db()
                break
            except PermissionError:
                reply = QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=get_db_path()), QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Cancel: return
        
        self.mw.library_controller.patch_memory_df(folder_name, game_obj.to_dict())
        self.mw.library_controller.update_status_checkboxes_state()
        self.mw.list_controller.update_single_card(folder_name, force_media_reload=True)
        self.mw.filter_controller.request_filter_update()
        self.mw.settings_controller.save_settings()

    def execute_merge(self, folder_a, folder_b):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game_a = manager.games.get(folder_a)
        game_b = manager.games.get(folder_b)
        if not game_a or not game_b: return False
        
        old_title = game_a.data.get('Clean_Title', '')
        old_year = game_a.data.get('Original_Release_Date', '')
        conflicts = game_a.merge_with(game_b)
        rejected_media = []

        if conflicts:
            dlg = ConflictDialog(game_a.data, game_b.data, conflicts, self.mw)
            if dlg.exec():
                resolutions = dlg.get_resolutions()
                for field, val in resolutions.items(): game_a.data[field] = val
                if 'Image_Link' in conflicts:
                    rejected = conflicts['Image_Link']['B'] if resolutions['Image_Link'] == conflicts['Image_Link']['A'] else conflicts['Image_Link']['A']
                    if rejected and os.path.exists(rejected): rejected_media.append(rejected)
                if 'Path_Video' in conflicts:
                    rejected = conflicts['Path_Video']['B'] if resolutions['Path_Video'] == conflicts['Path_Video']['A'] else conflicts['Path_Video']['A']
                    if rejected and os.path.exists(rejected): rejected_media.append(rejected)
            else: return False

        del manager.games[folder_b]
        game_a.update_media_filenames(old_title, old_year)
        game_a.data['Status_Flag'] = 'LOCKED'
        
        for f in rejected_media:
            try: os.remove(f)
            except: pass
                
        manager.save_db()
        self.mw.library_controller.patch_memory_df(folder_a, game_a.to_dict())
            
        self.mw.master_df = self.mw.master_df[self.mw.master_df['Folder_Name'] != folder_b]
        self.mw.current_df = self.mw.current_df[self.mw.current_df['Folder_Name'] != folder_b]
        self.mw.library_controller.update_status_checkboxes_state()

        self.mw.list_controller.update_single_card(folder_a, force_media_reload=True)
        self.mw.list_controller.remove_single_card(folder_b)
        self.mw.filter_controller.request_filter_update()
        self.mw.settings_controller.save_settings()
        return True

    def update_game_flags(self, folder_name, flags_dict):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        game = manager.games.get(folder_name)
        if game:
            for k, v in flags_dict.items(): game.data[k] = v
            manager.save_db()
            self.mw.library_controller.patch_memory_df(folder_name, flags_dict)
            self.mw.filter_controller.request_filter_update()

    def delete_game(self, folder_name):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        
        game_obj = manager.games.get(folder_name)
        if game_obj:
            img_name = game_obj.data.get('Image_Link', '')
            vid_name = game_obj.data.get('Path_Video', '')
            
            if img_name:
                try: os.remove(os.path.join(get_image_path(), os.path.basename(img_name)))
                except: pass
            if vid_name:
                try: os.remove(os.path.join(get_video_path(), os.path.basename(vid_name)))
                except: pass
                
            del manager.games[folder_name]
            manager.save_db()
            
        self.mw.master_df = self.mw.master_df[self.mw.master_df['Folder_Name'] != folder_name]
        self.mw.current_df = self.mw.current_df[self.mw.current_df['Folder_Name'] != folder_name]
        self.mw.list_controller.remove_single_card(folder_name)
        self.mw.library_controller.update_status_checkboxes_state()
        self.mw.settings_controller.save_settings()
        logging.info(f"{'Deleted':<15} : {folder_name}")

    def batch_delete_games(self, folder_names):
        for folder in folder_names: self.delete_game(folder)
        self.mw.list_controller.load_more_items()

    def batch_update_games(self, folder_names, new_data):
        for folder in folder_names: self.update_game_data(folder, new_data)

    def batch_delete_metadata(self, field, items_to_delete):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        items_set = set(items_to_delete)
        
        updated_folders = []
        for folder_name, game_obj in manager.games.items():
            current_val = game_obj.data.get(field, "")
            if not current_val: continue
            
            parts = [p.strip() for p in str(current_val).split(',')]
            new_parts = [p for p in parts if p not in items_set and p]
            
            if len(parts) != len(new_parts):
                game_obj.data[field] = ", ".join(new_parts)
                updated_folders.append(folder_name)
                
        if not updated_folders: return
        
        while True:
            try:
                manager.save_db()
                break
            except PermissionError:
                reply = QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=get_db_path()), QMessageBox.Ok | QMessageBox.Cancel)
                if reply == QMessageBox.Cancel: return
                
        for folder in updated_folders:
            self.mw.library_controller.patch_memory_df(folder, manager.games[folder].to_dict())
            # Safely update UI if visible
            self.mw.list_controller.update_single_card(folder, force_media_reload=False)
            
        self.mw.library_controller.update_status_checkboxes_state()
        self.mw.filter_controller.request_filter_update()
        self.mw.settings_controller.save_settings()

    def execute_batch_renames(self, approved_renames):
        manager = LibraryManager(build_scanner_config())
        manager.load_db()
        
        changes_made = False
        
        for rename_info in approved_renames:
            old_folder = rename_info['old_folder']
            new_folder = rename_info['new_folder']
            old_path_root = rename_info['path_root']
            
            if not old_path_root or not os.path.exists(old_path_root):
                logging.error(f"Cannot rename {old_folder}: Root path does not exist.")
                continue
                
            parent_dir = os.path.dirname(old_path_root)
            new_path_root = os.path.join(parent_dir, new_folder)
            
            if os.path.exists(new_path_root):
                logging.warning(f"Target folder {new_folder} already exists. Skipping.")
                continue
                
            try:
                temp_game = manager.games.get(old_folder)
                old_vid_path = None
                if temp_game:
                    # Fetch the old video path BEFORE renaming the folder, 
                    # otherwise get_local_trailer_path() will fail its os.path.exists check.
                    old_vid_path = temp_game.get_local_trailer_path()

                # 1. Rename physical folder
                os.rename(old_path_root, new_path_root)
                
                if temp_game:
                    # 2. Rename associated trailer video if it exists
                    if old_vid_path and os.path.exists(old_vid_path):
                        ext = os.path.splitext(old_vid_path)[1]
                        new_vid_path = os.path.join(parent_dir, f"{new_folder}{ext}")
                        os.rename(old_vid_path, new_vid_path)
                
                    # 3. Rename associated image file
                    if temp_game.data.get('Image_Link'):
                        old_img_name = temp_game.data['Image_Link']
                        old_img_path = os.path.join(get_image_path(), old_img_name)
                        if os.path.exists(old_img_path):
                            ext = os.path.splitext(old_img_path)[1]
                            new_img_name = f"{new_folder}{ext}"
                            new_img_path = os.path.join(get_image_path(), new_img_name)
                            if old_img_path != new_img_path and not os.path.exists(new_img_path):
                                os.rename(old_img_path, new_img_path)
                                temp_game.data['Image_Link'] = new_img_name
                
                    # 4. Update DB references
                    temp_game.data['Path_Root'] = new_path_root
                    temp_game.data['Folder_Name'] = new_folder
                    manager.games[new_folder] = temp_game
                    del manager.games[old_folder]
                    changes_made = True
                    
            except Exception as e:
                logging.error(f"Failed to rename {old_folder} to {new_folder}: {e}")
                
        if changes_made:
            while True:
                try:
                    manager.save_db()
                    break
                except PermissionError:
                    reply = QMessageBox.warning(self.mw, "File Locked", translator.tr("msg_file_locked", db_path=get_db_path()), QMessageBox.Ok | QMessageBox.Cancel)
                    if reply == QMessageBox.Cancel: return
                    
            if hasattr(self.mw, 'compile_db_and_refresh'):
                self.mw.compile_db_and_refresh()
            else:
                self.mw.library_controller.load_database_async()
            
            QMessageBox.information(self.mw, "Renames Applied", f"Successfully processed OS folder renames for {len(approved_renames)} games.")