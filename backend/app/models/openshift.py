"""
OpenShift Container Platform envanter modelleri — cluster, node, proje (namespace) ve workload (pod/deployment/route).
"""
from sqlalchemy import Column, Integer, String, JSON, DateTime, Float, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class OpenShiftCluster(Base):
    """OpenShift Container Platform cluster bağlantısı — API URL + Bearer Token."""
    __tablename__ = "openshift_clusters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    api_url = Column(String(500), nullable=False)
    connection_config = Column(JSON, nullable=False, default=dict)  # {token, verify_ssl}
    status = Column(String(50), default="unknown")
    version = Column(String(64), nullable=True)
    last_sync = Column(DateTime(timezone=True))
    meta_data = Column(JSON, nullable=True)  # sync_job progress vb.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    nodes = relationship("OpenShiftNode", back_populates="cluster", cascade="all, delete-orphan")
    projects = relationship("OpenShiftProject", back_populates="cluster", cascade="all, delete-orphan")
    workloads = relationship("OpenShiftWorkload", back_populates="cluster", cascade="all, delete-orphan")


class OpenShiftNode(Base):
    """Cluster node — master/worker/infra."""
    __tablename__ = "openshift_nodes"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("openshift_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    role = Column(String(32), default="worker")  # master | worker | infra
    status = Column(String(50), default="unknown")  # Ready | NotReady | ...
    cpu_cores = Column(Float, nullable=True)
    memory_gb = Column(Float, nullable=True)
    cpu_usage_pct = Column(Float, nullable=True)
    memory_usage_pct = Column(Float, nullable=True)
    kubelet_version = Column(String(64), nullable=True)
    os_image = Column(String(255), nullable=True)
    pod_count = Column(Integer, default=0)
    meta_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cluster = relationship("OpenShiftCluster", back_populates="nodes")


class OpenShiftProject(Base):
    """Proje / namespace."""
    __tablename__ = "openshift_projects"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("openshift_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    status = Column(String(50), default="Active")
    pod_count = Column(Integer, default=0)
    deployment_count = Column(Integer, default=0)
    route_count = Column(Integer, default=0)
    display_name = Column(String(255), nullable=True)
    requester = Column(String(255), nullable=True)
    meta_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cluster = relationship("OpenShiftCluster", back_populates="projects")


class OpenShiftWorkload(Base):
    """Pod / Deployment / Route düzeyinde envanter — durum ve sağlık özet bilgisi."""
    __tablename__ = "openshift_workloads"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("openshift_clusters.id", ondelete="CASCADE"), nullable=False, index=True)
    project = Column(String(255), nullable=False, index=True)
    kind = Column(String(32), nullable=False)  # pod | deployment | route
    name = Column(String(255), nullable=False, index=True)
    status = Column(String(64), default="unknown")
    node_name = Column(String(255), nullable=True)
    restart_count = Column(Integer, default=0)
    ready = Column(String(16), nullable=True)  # ör. "2/2"
    host = Column(String(255), nullable=True)  # route host (kind=route)
    meta_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    cluster = relationship("OpenShiftCluster", back_populates="workloads")
