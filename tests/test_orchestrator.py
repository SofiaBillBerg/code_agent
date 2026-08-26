import json
import xml.etree.ElementTree as ET

import pytest

from code_agent.agents.orchestrator import Orchestrator


@pytest.fixture
def temp_registry(tmp_path):
    registry = tmp_path / "registry.json"
    data = {"agents": [{"name": "test_agent"}], "workflows": []}
    registry.write_text(json.dumps(data))
    return registry


@pytest.fixture
def temp_orchestrator_xml(tmp_path):
    xml_path = tmp_path / "orchestrator.xml"
    root = ET.Element("orchestrator")
    tree = ET.ElementTree(root)
    tree.write(xml_path)
    return xml_path


def test_orchestrator_initialization(temp_registry, temp_orchestrator_xml):
    orch = Orchestrator(
        registry_path=str(temp_registry),
        orchestrator_xml=str(temp_orchestrator_xml),
    )
    assert orch.registry["agents"][0]["name"] == "test_agent"
    assert orch.orchestrator_config.tag == "orchestrator"


def test_orchestrator_route_to_agent(temp_registry, temp_orchestrator_xml):
    orch = Orchestrator(
        registry_path=str(temp_registry),
        orchestrator_xml=str(temp_orchestrator_xml),
    )
    agent = orch.route_to_agent("test_agent")
    assert agent["name"] == "test_agent"
