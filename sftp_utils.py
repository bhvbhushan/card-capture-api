import os
import logging
import paramiko
from typing import Optional
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SFTPConfig:
    """Configuration class for SFTP settings"""
    def __init__(self):
        self.host = os.getenv('SLATE_SFTP_HOST', 'ft.technolutions.net')
        self.port = int(os.getenv('SLATE_SFTP_PORT', '22'))
        # Extract username from email if it contains @
        full_username = os.getenv('SLATE_SFTP_USERNAME', 'cardcapture@apply.mcm.edu')
        self.username = full_username.split('@')[0] if '@' in full_username else full_username
        self.password = os.getenv('SLATE_SFTP_PASSWORD', '3bbc68f1460047579e610c194a8bec26')
        self.upload_path = os.getenv('SLATE_SFTP_UPLOAD_PATH', '/test/incoming/cardcapture')
        self.key_path = os.getenv('SLATE_SFTP_KEY_PATH')  # Optional key-based auth

def upload_to_slate(csv_file_path: str, config: Optional[SFTPConfig] = None) -> bool:
    """
    Upload a CSV file to Slate SFTP server.
    
    Args:
        csv_file_path (str): Path to the CSV file to upload
        config (Optional[SFTPConfig]): SFTP configuration. If None, uses default config.
    
    Returns:
        bool: True if upload successful, False otherwise
    """
    if not config:
        config = SFTPConfig()
    
    if not os.path.exists(csv_file_path):
        logger.error(f"CSV file not found: {csv_file_path}")
        return False
    
    try:
        # Initialize SSH client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect to SFTP server
        logger.info(f"Connecting to SFTP server: {config.host}")
        
        # Use password authentication only
        logger.info("Using password authentication...")
        ssh.connect(
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            look_for_keys=False,  # Disable looking for keys
            allow_agent=False     # Disable SSH agent
        )
        
        # Open SFTP session
        sftp = ssh.open_sftp()
        
        # Ensure upload directory exists
        try:
            sftp.stat(config.upload_path)
        except FileNotFoundError:
            logger.info(f"Creating upload directory: {config.upload_path}")
            sftp.mkdir(config.upload_path)
        
        # Get filename from path
        filename = Path(csv_file_path).name
        
        # Construct full remote path
        remote_path = f"{config.upload_path}/{filename}"
        
        # Upload file
        logger.info(f"Uploading {filename} to {remote_path}")
        sftp.put(csv_file_path, remote_path)
        
        # Close connections
        sftp.close()
        ssh.close()
        
        logger.info("File uploaded successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return False
    finally:
        try:
            sftp.close()
            ssh.close()
        except:
            pass

def test_connection(config: Optional[SFTPConfig] = None) -> bool:
    """
    Test SFTP connection without uploading any files.
    
    Args:
        config (Optional[SFTPConfig]): SFTP configuration. If None, uses default config.
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    if not config:
        config = SFTPConfig()
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Use password authentication only
        ssh.connect(
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            look_for_keys=False,  # Disable looking for keys
            allow_agent=False     # Disable SSH agent
        )
        
        sftp = ssh.open_sftp()
        sftp.listdir(config.upload_path)
        
        sftp.close()
        ssh.close()
        
        logger.info("SFTP connection test successful")
        return True
        
    except Exception as e:
        logger.error(f"SFTP connection test failed: {str(e)}")
        return False
    finally:
        try:
            sftp.close()
            ssh.close()
        except:
            pass 