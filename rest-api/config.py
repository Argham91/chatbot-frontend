DEPARTMENT_TABLE_MAP = {
    "mines": ["mine_sites", "ore_extraction_logs", "drilling_reports", "production_output"],

    "raw_material_handling": ["material_receipts", "stockyard_inventory", "material_transfer_logs"],

    "ferro_alloy_production": ["furnace_operations", "heat_logs", "production_batches", "output_quality"],

    "chrome_recovery_plant": ["slag_processing", "recovery_yield", "crp_batches"],

    "sinter_plant": ["sinter_batches", "raw_mix_data", "sinter_quality_reports"],

    "power_plant": ["power_generation_logs", "fuel_consumption", "load_distribution"],

    "utilities": ["water_usage", "compressed_air_logs", "gas_supply_records"],

    "maintenance_mechanical": ["equipment_logs", "maintenance_schedule", "breakdown_reports"],

    "maintenance_electrical": ["electrical_maintenance", "fault_logs", "power_equipment_status"],

    "instrumentation_automation": ["sensor_data", "plc_logs", "control_system_alerts"],

    "quality_control": ["lab_tests", "material_analysis", "quality_reports"],

    "research_development": ["experiment_data", "process_improvements", "r_and_d_projects"],

    "process_engineering": ["process_parameters", "efficiency_reports", "optimization_logs"],

    "procurement": ["purchase_orders", "vendor_master", "procurement_requests"],

    "stores_inventory": ["inventory_stock", "material_issues", "warehouse_logs"],

    "logistics_dispatch": ["shipment_details", "transport_logs", "dispatch_records"],

    "export_commercial": ["export_orders", "contracts", "customer_invoices"],

    "hr": ["employees", "payroll", "leave_requests", "benefits"],

    "finance": ["budgets", "expenses", "invoices", "financial_reports"],

    "it": ["support_tickets", "asset_inventory", "software_licenses"],

    "legal_compliance": ["contracts", "compliance_records", "legal_cases"],

    "administration": ["facility_management", "office_assets", "admin_requests"],

    "health_safety_environment": ["incident_reports", "safety_audits", "environment_data"],

    "security": ["access_logs", "visitor_records", "security_incidents"],

    "csr": ["csr_projects", "community_programs", "impact_reports"]
}

DEPARTMENT_DESCRIPTIONS = {
    "mines": "Handles queries related to mining operations, ore extraction, and production output.",

    "raw_material_handling": "Handles queries about material receipt, storage, and internal movement.",

    "ferro_alloy_production": "Handles queries about furnace operations, production batches, and output quality.",

    "chrome_recovery_plant": "Handles queries about slag processing and metal recovery operations.",

    "sinter_plant": "Handles queries about sinter production, raw mix, and quality control.",

    "power_plant": "Handles queries about power generation, fuel consumption, and load distribution.",

    "utilities": "Handles queries about water, compressed air, and gas supply systems.",

    "maintenance_mechanical": "Handles queries about mechanical equipment maintenance and breakdowns.",

    "maintenance_electrical": "Handles queries about electrical systems, faults, and maintenance.",

    "instrumentation_automation": "Handles queries about sensors, PLC systems, and automation alerts.",

    "quality_control": "Handles queries about lab testing, material quality, and inspection reports.",

    "research_development": "Handles queries about innovation, experiments, and process improvements.",

    "process_engineering": "Handles queries about process optimization and efficiency improvements.",

    "procurement": "Handles queries about purchase orders, vendors, and procurement processes.",

    "stores_inventory": "Handles queries about inventory levels, stock movement, and warehouse data.",

    "logistics_dispatch": "Handles queries about shipment, transportation, and dispatch records.",

    "export_commercial": "Handles queries about export orders, contracts, and customer billing.",

    "hr": "Handles queries about employees, payroll, recruitment, and leave management.",

    "finance": "Handles queries about budgets, expenses, invoices, and financial reports.",

    "it": "Handles queries about technical support, IT assets, and software systems.",

    "legal_compliance": "Handles queries about contracts, legal matters, and regulatory compliance.",

    "administration": "Handles queries about office operations, facilities, and admin services.",

    "health_safety_environment": "Handles queries about safety incidents, audits, and environmental compliance.",

    "security": "Handles queries about access control, visitor logs, and security incidents.",

    "csr": "Handles queries about corporate social responsibility initiatives and community programs."
}

# Guardrails
FORBIDDEN_SQL = ["DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE"]
MAX_ROWS = 100
MAX_RETRIES = 2

ROLE_PERMISSIONS = {
    "admin": ["*"],

    "manager": [
        "hr", "finance", "procurement", "logistics_dispatch"
    ],

    "engineer": [
        "mines", "ferro_alloy_production", "maintenance_mechanical"
    ],

    "employee": [
        "hr"
    ]
}