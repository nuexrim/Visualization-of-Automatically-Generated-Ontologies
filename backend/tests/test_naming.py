from backend.ontology import naming


def test_class_name():
    assert naming.to_class_name("film_actor") == "FilmActor"
    assert naming.to_class_name("all_prevalences") == "AllPrevalences"
    assert str(naming.class_iri("film_text")) == "http://example.org/ontology#FilmText"


def test_data_property_name_is_table_scoped_and_iri_safe():
    assert naming.data_property_name("film", "title") == "film_title"
    assert naming.data_property_name("all_prevalences", "POPULATION TYPE") == "all_prevalences_POPULATION_TYPE"


def test_object_property_name():
    assert naming.object_property_name("rental", "inventory_id", "inventory") == "rental_hasInventory"
    assert naming.object_property_name("store", "manager_staff_id", "staff") == "store_hasManagerStaff"
    # 'id'로 끝나지 않으면 참조 테이블 이름을 쓴다
    assert naming.object_property_name("allergies", "PATIENT", "patients") == "allergies_hasPatients"
    # 자기참조는 컬럼 이름 그대로
    assert naming.object_property_name("employee", "reports_to", "employee") == "employee_reports_to"


def test_provenance_round_trip():
    for table, column in [("film", None), ("film", "title"), ("all_prevalences", "POPULATION TYPE")]:
        assert naming.parse_provenance(naming.provenance_iri(table, column)) == (table, column)
    assert " " not in str(naming.provenance_iri("all_prevalences", "POPULATION TYPE"))
    assert naming.parse_provenance("http://example.org/ontology#Film") is None
