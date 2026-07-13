"""
Server schemas
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class ServerCreate(BaseModel):
    """Server creation schema"""
    name: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = "unknown"
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    server_type: Optional[str] = None
    cpu_cores: Optional[int] = 0
    memory_gb: Optional[int] = 0
    ai_ready: Optional[bool] = False
    connection_config: Optional[Dict[str, Any]] = {}

class ServerUpdate(BaseModel):
    """Server update schema"""
    name: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    server_type: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    ai_ready: Optional[bool] = None
    connection_config: Optional[Dict[str, Any]] = None

class ServerResponse(BaseModel):
    """Server response schema"""
    id: int
    name: str
    hostname: Optional[str]
    ip_address: Optional[str]
    status: Optional[str]
    os_type: Optional[str]
    os_version: Optional[str]
    server_type: Optional[str]
    cpu_cores: Optional[int]
    memory_gb: Optional[int]
    ai_ready: Optional[bool]
    connection_config: Optional[Dict[str, Any]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
