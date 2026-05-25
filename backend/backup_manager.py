import os
import io
import json
import zipfile
import logging
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# WHY: Single Responsibility Principle - Handles the compression and encryption of the .vgv backup format.
# DRY Principle - Centralizes encryption logic to match the Dart mobile implementation.

APP_KEY = b'ViGaVault_App_Vault_Secret_Key!!' # 32 bytes
APP_IV = b'VGV_App_Init_Vec' # 16 bytes

def _get_cipher():
    # WHY: Dart's `encrypt` package defaults to AES in SIC (CTR) mode.
    # We use the cryptography package's CTR mode which corresponds to SIC.
    return Cipher(algorithms.AES(APP_KEY), modes.CTR(APP_IV), backend=default_backend())

def create_vgv_backup(db_path, images_path, global_settings, lib_settings, output_path):
    """
    Creates an AES-256 encrypted .vgv archive containing the database, images, and unified settings.
    """
    archive_buffer = io.BytesIO()
    
    # WHY: Use ZIP_DEFLATED to compress the contents before encrypting, saving space on large image libraries.
    with zipfile.ZipFile(archive_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Snapshot Database
        if os.path.exists(db_path):
            db_filename = os.path.basename(db_path)
            zf.write(db_path, db_filename)
        
        # 2. Snapshot Images
        if os.path.exists(images_path):
            for root, _, files in os.walk(images_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname = f"images/{file}"
                    zf.write(full_path, arcname)
        
        # 3. Snapshot Settings
        unified_settings = {**global_settings, **lib_settings}
        settings_json = json.dumps(unified_settings, indent=4)
        zf.writestr("settings.json", settings_json)
        
        # 4. Snapshot Session Files (Credentials)
        if global_settings or lib_settings:
            import ViGaVault_utils
            backend_dir = os.path.join(ViGaVault_utils.BASE_DIR, "backend")
            if os.path.exists(backend_dir):
                for root, _, files in os.walk(backend_dir):
                    for file in files:
                        if file.endswith("_session.dat"):
                            full_path = os.path.join(root, file)
                            arcname = f"sessions/{file}"
                            zf.write(full_path, arcname)
        
    zip_bytes = archive_buffer.getvalue()
    
    # Encrypt the ZIP buffer
    encryptor = _get_cipher().encryptor()
    encrypted_bytes = encryptor.update(zip_bytes) + encryptor.finalize()
    
    # Write to disk
    with open(output_path, 'wb') as f:
        f.write(encrypted_bytes)
        
    logging.info(f"Successfully created encrypted backup at {output_path}")

def analyze_vgv_backup(backup_path):
    """
    Pre-scans the archive to inform the UI what modules are available.
    """
    with open(backup_path, 'rb') as f:
        encrypted_bytes = f.read()
        
    decryptor = _get_cipher().decryptor()
    decrypted_bytes = decryptor.update(encrypted_bytes) + decryptor.finalize()
    
    archive_buffer = io.BytesIO(decrypted_bytes)
    has_db = False
    has_images = False
    has_settings = False
    
    try:
        with zipfile.ZipFile(archive_buffer, 'r') as zf:
            for name in zf.namelist():
                name_lower = name.lower()
                if name_lower.endswith('.dat') or name_lower == 'vigavault.db':
                    has_db = True
                elif name_lower.startswith('images/'):
                    has_images = True
                elif name_lower == 'settings.json':
                    has_settings = True
    except zipfile.BadZipFile:
        logging.error("Failed to parse the decrypted .vgv file. It may be corrupt or encrypted with a different key.")
        return None
        
    return {
        'hasDb': has_db,
        'hasImages': has_images,
        'hasSettings': has_settings
    }

def restore_vgv_backup(backup_path, restore_db=True, restore_images=True, restore_settings=True, target_db_path=None, target_img_dir=None):
    """
    Extracts the selected modules from the encrypted .vgv archive.
    """
    with open(backup_path, 'rb') as f:
        encrypted_bytes = f.read()
        
    decryptor = _get_cipher().decryptor()
    decrypted_bytes = decryptor.update(encrypted_bytes) + decryptor.finalize()
    
    archive_buffer = io.BytesIO(decrypted_bytes)
    restored_global = {}
    restored_lib = {}
    restored_db_path = None
    
    # The global keys expected to be routed to the global settings.bin file
    GLOBAL_KEYS = ["geometry", "theme", "language", "cardImageSize", "cardButtonSize", "cardTextSize", "libraryName", "splitterSizes", "dateFormat"]
    
    try:
        with zipfile.ZipFile(archive_buffer, 'r') as zf:
            for name in zf.namelist():
                name_lower = name.lower()
                if restore_db and not name_lower.startswith('sessions/') and (name_lower.endswith('.dat') or name_lower == 'vigavault.db'):
                    if target_db_path:
                        # Ensure the target database directory exists
                        os.makedirs(os.path.dirname(target_db_path), exist_ok=True)
                        # Decrypt and write the database bytes directly to the exact target path
                        file_data = zf.read(name)
                        with open(target_db_path, 'wb') as db_f:
                            db_f.write(file_data)
                        restored_db_path = target_db_path
                
                elif restore_images and name_lower.startswith('images/'):
                    if target_img_dir:
                        # Ensure the target base images directory exists
                        os.makedirs(target_img_dir, exist_ok=True)
                        # Extract the specific file into the target directory
                        file_data = zf.read(name)
                        filename = os.path.basename(name)
                        if filename:
                            with open(os.path.join(target_img_dir, filename), 'wb') as img_f:
                                img_f.write(file_data)
                                
                elif restore_settings and name_lower.startswith('sessions/'):
                    import ViGaVault_utils
                    filename = os.path.basename(name)
                    if filename:
                        platform_name = filename.split('_')[0]
                        dest_dir = os.path.join(ViGaVault_utils.BASE_DIR, "backend", platform_name)
                        os.makedirs(dest_dir, exist_ok=True)
                        
                        file_data = zf.read(name)
                        dest_path = os.path.join(dest_dir, filename)
                        with open(dest_path, 'wb') as session_f:
                            session_f.write(file_data)
                                
                elif restore_settings and name_lower == 'settings.json':
                    settings_data = zf.read(name).decode('utf-8')
                    try:
                        restored_settings = json.loads(settings_data)
                        for k, v in restored_settings.items():
                            if k in GLOBAL_KEYS:
                                restored_global[k] = v
                            else:
                                restored_lib[k] = v
                    except json.JSONDecodeError:
                        logging.error("Failed to parse settings.json in backup.")
                        
    except zipfile.BadZipFile:
        logging.error("Failed to extract the decrypted .vgv file.")
        raise Exception("INVALID_BACKUP_FORMAT")
        
    return {
        'global_settings': restored_global if restore_settings else None,
        'lib_settings': restored_lib if restore_settings else None,
        'db_path': restored_db_path
    }
