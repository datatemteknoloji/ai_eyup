from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class PkgSubscription(SQLModel, table=True):
    """OS major'a bağlı opsiyonel activation key (yoksa wipe/register atlanır)."""

    __tablename__ = "pkg_subscriptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(default="", max_length=128)
    os_id: str = Field(default="rhel", max_length=64, index=True)
    os_major: str = Field(default="", max_length=16, index=True)
    org: str = Field(default="", max_length=255)
    activation_key_enc: str = Field(default="", max_length=4096)
    enabled: bool = Field(default=True)


class PkgLocalRepo(SQLModel, table=True):
    """Keyword'lü local repo: NFS mount veya portal dosya (RPM) + post komutlar; OS major'a bağlı."""

    __tablename__ = "pkg_local_repos"

    id: Optional[int] = Field(default=None, primary_key=True)
    keyword: str = Field(max_length=64, index=True)
    label: str = Field(default="", max_length=128)
    os_id: str = Field(default="rhel", max_length=64, index=True)
    os_major: str = Field(default="", max_length=16, index=True)
    # nfs | portal_files | subscription
    source_type: str = Field(default="nfs", max_length=32)
    nfs_path: str = Field(default="", max_length=512)
    mount_point: str = Field(default="", max_length=512)
    repo_id: str = Field(default="", max_length=64)
    baseurl_suffix: str = Field(default="", max_length=255)
    # portal_files: uygulama sunucusundaki dizin + glob
    portal_path: str = Field(default="", max_length=512)
    file_glob: str = Field(default="*.rpm", max_length=128)
    needs_data_mount: bool = Field(default=False)
    post_commands: str = Field(default="", sa_column=Column(Text, default=""))
    enabled: bool = Field(default=True)


# Eski tablolar (create_all uyumu; yeni kod kullanmaz)
class OsPackageProfile(SQLModel, table=True):
    __tablename__ = "os_package_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=64, unique=True, index=True)
    match_os_id: str = Field(default="rhel", max_length=64)
    match_version_major: str = Field(default="", max_length=16)
    enabled: bool = Field(default=True)


class SubscriptionSource(SQLModel, table=True):
    __tablename__ = "subscription_sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(default=0, index=True)
    org: str = Field(default="", max_length=255)
    activation_key_enc: str = Field(default="", max_length=4096)
    enabled: bool = Field(default=True)


class LocalRepoSource(SQLModel, table=True):
    __tablename__ = "local_repo_sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(default=0, index=True)
    keyword: str = Field(default="", max_length=64, index=True)
    label: str = Field(default="", max_length=128)
    nfs_path: str = Field(default="", max_length=512)
    mount_point: str = Field(default="", max_length=512)
    repo_id: str = Field(default="", max_length=64)
    baseurl_suffix: str = Field(default="", max_length=255)
    enabled: bool = Field(default=True)
