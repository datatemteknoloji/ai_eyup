"""
Hypervisor schemas
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class HypervisorCreate(BaseModel):
    """Hypervisor creation schema"""
    name: str
    type: str  # vmware, hyperv, kvm, xen (required, maps to hypervisor_type enum)
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    connection_config: Optional[Dict[str, Any]] = {}

class HypervisorUpdate(BaseModel):
    """Hypervisor update schema"""
    name: Optional[str] = None
    type: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    connection_config: Optional[Dict[str, Any]] = None

class HypervisorResponse(BaseModel):
    """Hypervisor response schema"""
    id: int
    name: str
    type: Optional[str]
    hostname: Optional[str]
    ip_address: Optional[str]
    port: Optional[int]
    username: Optional[str]
    connection_config: Optional[Dict[str, Any]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
