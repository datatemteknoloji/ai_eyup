"""
Jenerik vSphere okuma katmanı ve sağlık/cluster türetmeleri için birim testler.

Bu katman canlı vCenter olmadan test edilebilsin diye SOAP gövdeleri sabit
XML olarak verilir; ağ çağrısı yapılmaz.
"""
import xml.etree.ElementTree as ET

import pytest

from app.services.vmware.vcenter_client import VCenterClient
from app.services.vmware.perf_catalog import (
    METRIC_BUNDLES, is_mutate_method, resolve_metric_keys, SOAP_READ_ALLOW,
)


@pytest.fixture
def client() -> VCenterClient:
    # Ağ kullanılmaz; yalnızca saf parse/normalize metodları test edilir.
    return VCenterClient.__new__(VCenterClient)


CLUSTER_XML = """<returnval xmlns="urn:vim25" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <obj type="ClusterComputeResource">domain-c7</obj>
  <propSet><name>name</name><val>PROD-CL</val></propSet>
  <propSet><name>host</name><val xsi:type="ArrayOfManagedObjectReference">
      <ManagedObjectReference type="HostSystem">host-11</ManagedObjectReference>
      <ManagedObjectReference type="HostSystem">host-12</ManagedObjectReference>
  </val></propSet>
  <propSet><name>configurationEx</name><val xsi:type="ClusterConfigInfoEx">
      <dasConfig>
        <enabled>true</enabled>
        <admissionControlEnabled>true</admissionControlEnabled>
        <admissionControlPolicy xsi:type="ClusterFailoverResourcesAdmissionControlPolicy">
          <cpuFailoverResourcesPercent>25</cpuFailoverResourcesPercent>
          <memoryFailoverResourcesPercent>25</memoryFailoverResourcesPercent>
        </admissionControlPolicy>
        <hostMonitoring>enabled</hostMonitoring>
        <vmMonitoring>vmMonitoringOnly</vmMonitoring>
      </dasConfig>
      <drsConfig>
        <enabled>true</enabled>
        <defaultVmBehavior>fullyAutomated</defaultVmBehavior>
        <vmotionRate>3</vmotionRate>
      </drsConfig>
  </val></propSet>
</returnval>"""

SENSOR_XML = """<returnval xmlns="urn:vim25" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <obj type="HostSystem">host-8</obj>
  <propSet><name>name</name><val>esx01</val></propSet>
  <propSet><name>summary.overallStatus</name><val>red</val></propSet>
  <propSet><name>runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo</name>
    <val xsi:type="ArrayOfHostNumericSensorInfo">
      <HostNumericSensorInfo>
        <name>Power Supply 2</name><sensorType>power</sensorType>
        <healthState><key>red</key><label>Red</label></healthState>
        <currentReading>30</currentReading><unitModifier>-1</unitModifier>
        <baseUnits>Watts</baseUnits>
      </HostNumericSensorInfo>
      <HostNumericSensorInfo>
        <name>CPU1 Temp</name><sensorType>temperature</sensorType>
        <healthState><key>green</key></healthState>
        <currentReading>420</currentReading><unitModifier>-1</unitModifier>
        <baseUnits>Degrees C</baseUnits>
      </HostNumericSensorInfo>
    </val></propSet>
</returnval>"""


def test_array_property_parsed_as_list(client):
    props = client._soap_returnval_props(ET.fromstring(CLUSTER_XML))
    assert props["_ref"] == "domain-c7"
    assert props["_type"] == "ClusterComputeResource"
    assert props["host"] == ["host-11", "host-12"]


def test_nested_struct_survives_parse(client):
    """Eski düzleştirici parser iç içe struct'ları kaybediyordu."""
    props = client._soap_returnval_props(ET.fromstring(CLUSTER_XML))
    cfg = props["configurationEx"]
    assert cfg["dasConfig"]["enabled"] is True
    assert cfg["drsConfig"]["defaultVmBehavior"] == "fullyAutomated"
    assert cfg["drsConfig"]["vmotionRate"] == "3"


def test_polymorphic_type_is_preserved(client):
    props = client._soap_returnval_props(ET.fromstring(CLUSTER_XML))
    policy = props["configurationEx"]["dasConfig"]["admissionControlPolicy"]
    assert policy["_type"] == "ClusterFailoverResourcesAdmissionControlPolicy"


def test_admission_policy_summary_percentage():
    policy = {
        "_type": "ClusterFailoverResourcesAdmissionControlPolicy",
        "cpuFailoverResourcesPercent": "25",
        "memoryFailoverResourcesPercent": "30",
    }
    out = VCenterClient._admission_policy_summary(policy)
    assert out["cpu_failover_pct"] == 25
    assert out["mem_failover_pct"] == 30
    assert out["policy_label"] == "Cluster resource percentage"


def test_admission_policy_summary_slot_based():
    out = VCenterClient._admission_policy_summary({
        "_type": "ClusterFailoverLevelAdmissionControlPolicy",
        "failoverLevel": "1",
    })
    assert out["failover_level"] == 1
    assert "slot" in out["policy_label"].lower()


def test_sensor_parse_reports_only_bad_sensors(client):
    props = client._soap_returnval_props(ET.fromstring(SENSOR_XML))
    sensors = props["runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo"]
    assert len(sensors) == 2
    bad = [
        s for s in sensors
        if str(s["healthState"]["key"]).lower() not in client._SENSOR_OK_STATES
    ]
    assert [s["name"] for s in bad] == ["Power Supply 2"]
    # unitModifier ile ölçek: 30 * 10^-1 = 3.0 Watts
    assert float(bad[0]["currentReading"]) * (10 ** float(bad[0]["unitModifier"])) == 3.0


def test_invalid_property_extracted_from_fault():
    fault = (
        '<soapenv:Fault xmlns:soapenv="x"><detail>'
        '<InvalidPropertyFault xmlns="urn:vim25" xsi:type="InvalidProperty">'
        "<name>summary.numVmotions</name></InvalidPropertyFault>"
        "</detail></soapenv:Fault>"
    )
    assert VCenterClient._invalid_property_from_fault(fault) == "summary.numVmotions"
    assert VCenterClient._invalid_property_from_fault("<ok/>") is None


def test_new_perf_counters_resolvable():
    """Latency ayrıştırma / bellek baskısı / contention paketleri katalogda olmalı."""
    host = resolve_metric_keys(["latency_breakdown"], entity="host")["keys"]
    assert "disk_device_latency_ms" in host
    assert "disk_queue_latency_ms" in host
    assert "disk_kernel_latency_ms" in host

    vm = resolve_metric_keys(["mem_pressure", "contention"], entity="vm")["keys"]
    assert "mem_balloon_kb" in vm
    assert "mem_swapout_rate_kbps" in vm
    assert "cpu_costop_ms" in vm

    net = resolve_metric_keys(["net"], entity="vm")["keys"]
    assert "net_dropped_rx" in net and "net_dropped_tx" in net


def test_read_allow_list_covers_new_soap_calls():
    for method in ("CreateContainerView", "DestroyView", "RetrieveDasAdvancedRuntimeInfo"):
        assert method in SOAP_READ_ALLOW
        assert not is_mutate_method(method)


def test_bundle_names_stable():
    for bundle in ("latency_breakdown", "mem_pressure", "contention", "ds_iops"):
        assert bundle in METRIC_BUNDLES
