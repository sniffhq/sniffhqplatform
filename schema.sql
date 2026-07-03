-- SniffHQ tenant schema — generated from app/models.py
-- Apply to a fresh SQLite DB to initialise a new tenant.
-- Order respects FK dependencies (SQLite doesn't enforce FKs by default,
-- but this ordering keeps things clean).

CREATE TABLE IF NOT EXISTS import_batch (
    id INTEGER NOT NULL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(64) NOT NULL,
    source_preset VARCHAR(30) NOT NULL DEFAULT 'generic',
    status VARCHAR(20) NOT NULL DEFAULT 'staged',
    dupe_strategy VARCHAR(20) NOT NULL DEFAULT 'skip',
    mapping_json TEXT NOT NULL DEFAULT '{}',
    customers_created INTEGER DEFAULT 0,
    customers_updated INTEGER DEFAULT 0,
    pets_created INTEGER DEFAULT 0,
    vaccinations_created INTEGER DEFAULT 0,
    rows_skipped INTEGER DEFAULT 0,
    total_rows INTEGER DEFAULT 0,
    created_by INTEGER,
    created_at DATETIME,
    committed_at DATETIME,
    undone_at DATETIME
);

CREATE TABLE IF NOT EXISTS play_group (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    size_category VARCHAR(20) NOT NULL,
    temperament VARCHAR(20) NOT NULL,
    max_capacity INTEGER DEFAULT 10,
    active BOOLEAN DEFAULT 1,
    color VARCHAR(7) DEFAULT '#0d6efd',
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS user (
    id INTEGER NOT NULL PRIMARY KEY,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255),
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    phone VARCHAR(20),
    address VARCHAR(200),
    city VARCHAR(100),
    state VARCHAR(2),
    zip_code VARCHAR(10),
    emergency_contact_name VARCHAR(100),
    emergency_contact_phone VARCHAR(20),
    how_heard VARCHAR(100),
    preferences TEXT,
    is_admin BOOLEAN DEFAULT 0,
    role VARCHAR(20) NOT NULL DEFAULT 'customer',
    is_active BOOLEAN DEFAULT 1,
    onboarding_complete BOOLEAN DEFAULT 0,
    created_at DATETIME,
    archived_at DATETIME,
    sms_opt_in BOOLEAN DEFAULT 0,
    email_opt_out BOOLEAN DEFAULT 0,
    staff_notes TEXT,
    custom_boarding_rate NUMERIC(10, 2),
    custom_boarding_rate_additional NUMERIC(10, 2),
    custom_daycare_rate NUMERIC(10, 2),
    custom_addon_spa_bath_nails NUMERIC(10, 2),
    custom_addon_spa_bath NUMERIC(10, 2),
    custom_addon_nail_trim NUMERIC(10, 2),
    custom_rate_note VARCHAR(255),
    import_batch_id INTEGER REFERENCES import_batch (id),
    staff_pin_hash VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS ix_user_import_batch_id ON user (import_batch_id);

CREATE TABLE IF NOT EXISTS shift_type (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    color VARCHAR(7) NOT NULL DEFAULT '#3DBDB5',
    default_start VARCHAR(5),
    default_end VARCHAR(5),
    description VARCHAR(200),
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS staff_shift (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    shift_type_id INTEGER REFERENCES shift_type (id),
    shift_date DATE NOT NULL,
    start_time VARCHAR(5) NOT NULL,
    end_time VARCHAR(5) NOT NULL,
    notes TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_staff_shift_user_id ON staff_shift (user_id);
CREATE INDEX IF NOT EXISTS ix_staff_shift_shift_date ON staff_shift (shift_date);

CREATE TABLE IF NOT EXISTS time_clock_entry (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    clock_in DATETIME NOT NULL,
    clock_out DATETIME,
    shift_id INTEGER REFERENCES staff_shift (id),
    notes TEXT,
    is_approved BOOLEAN DEFAULT 0,
    approved_by INTEGER REFERENCES user (id),
    approved_at DATETIME,
    overtime_flag BOOLEAN DEFAULT 0,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_time_clock_entry_user_id ON time_clock_entry (user_id);

CREATE TABLE IF NOT EXISTS staff_task_template (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(30) NOT NULL DEFAULT 'general',
    shift_slot VARCHAR(20) NOT NULL DEFAULT 'any',
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS staff_task_assignment (
    id INTEGER NOT NULL PRIMARY KEY,
    template_id INTEGER REFERENCES staff_task_template (id),
    task_name VARCHAR(100) NOT NULL,
    task_description TEXT,
    category VARCHAR(30) DEFAULT 'general',
    task_date DATE NOT NULL,
    assigned_to_id INTEGER REFERENCES user (id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    completed_at DATETIME,
    completed_by_id INTEGER REFERENCES user (id),
    completion_note TEXT,
    priority INTEGER DEFAULT 0,
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_staff_task_assignment_task_date ON staff_task_assignment (task_date);

CREATE TABLE IF NOT EXISTS staff_certification (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    cert_name VARCHAR(100) NOT NULL,
    issuing_org VARCHAR(100),
    issued_date DATE,
    expiry_date DATE,
    document_path VARCHAR(255),
    notes TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_staff_certification_user_id ON staff_certification (user_id);

CREATE TABLE IF NOT EXISTS staff_performance_note (
    id INTEGER NOT NULL PRIMARY KEY,
    subject_user_id INTEGER NOT NULL REFERENCES user (id),
    author_id INTEGER NOT NULL REFERENCES user (id),
    note_type VARCHAR(20) NOT NULL DEFAULT 'general',
    note_text TEXT NOT NULL,
    is_private BOOLEAN DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_staff_performance_note_subject_user_id ON staff_performance_note (subject_user_id);

CREATE TABLE IF NOT EXISTS time_off_request (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    request_type VARCHAR(20) NOT NULL DEFAULT 'vacation',
    reason TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewed_by INTEGER REFERENCES user (id),
    reviewed_at DATETIME,
    admin_notes TEXT,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_time_off_request_user_id ON time_off_request (user_id);

CREATE TABLE IF NOT EXISTS waiver_template (
    id INTEGER NOT NULL PRIMARY KEY,
    slug VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    version VARCHAR(20) NOT NULL DEFAULT '1.0',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS signed_waiver (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    template_id INTEGER NOT NULL REFERENCES waiver_template (id),
    waiver_version VARCHAR(20) NOT NULL,
    signature_data TEXT NOT NULL,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    signed_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_signed_waiver_user_id ON signed_waiver (user_id);

CREATE TABLE IF NOT EXISTS service_type (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    base_price NUMERIC(10, 2) NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    description VARCHAR(200),
    icon VARCHAR(60) DEFAULT 'fa-tag',
    customer_bookable BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payment (
    id INTEGER NOT NULL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES user (id),
    amount FLOAT NOT NULL,
    payment_date DATE NOT NULL,
    service_type VARCHAR(50),
    payment_method VARCHAR(30),
    notes TEXT,
    status VARCHAR(20) DEFAULT 'paid',
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS pet (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    name VARCHAR(100) NOT NULL,
    breed VARCHAR(100),
    age INTEGER,
    weight NUMERIC(5, 2),
    special_instructions TEXT,
    photo_filename VARCHAR(255),
    vaccination_record VARCHAR(255),
    vet_name VARCHAR(100),
    vet_phone VARCHAR(20),
    gender VARCHAR(10),
    spayed_neutered BOOLEAN DEFAULT 0,
    microchipped BOOLEAN DEFAULT 0,
    microchip_number VARCHAR(50),
    medical_notes TEXT,
    additional_notes TEXT,
    photo_path VARCHAR(255),
    vaccination_record_path VARCHAR(255),
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME,
    archived_at DATETIME,
    temperament VARCHAR(20) DEFAULT 'calm',
    date_of_birth DATE,
    default_play_group_id INTEGER REFERENCES play_group (id),
    import_batch_id INTEGER REFERENCES import_batch (id)
);

CREATE INDEX IF NOT EXISTS ix_pet_import_batch_id ON pet (import_batch_id);

CREATE TABLE IF NOT EXISTS appointment (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    service_type_id INTEGER NOT NULL REFERENCES service_type (id),
    appointment_date DATE,
    start_time DATETIME,
    end_time DATETIME,
    status VARCHAR(20) DEFAULT 'pending',
    notes TEXT,
    created_at DATETIME,
    archived BOOLEAN DEFAULT 0,
    payment_id INTEGER REFERENCES payment (id)
);

CREATE TABLE IF NOT EXISTS service_block (
    id INTEGER NOT NULL PRIMARY KEY,
    service_type_id INTEGER NOT NULL REFERENCES service_type (id),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason VARCHAR(200),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS daycare_enrollment (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    enrollment_date DATE NOT NULL,
    active BOOLEAN DEFAULT 1,
    notes TEXT,
    monday BOOLEAN DEFAULT 0,
    tuesday BOOLEAN DEFAULT 0,
    wednesday BOOLEAN DEFAULT 0,
    thursday BOOLEAN DEFAULT 0,
    friday BOOLEAN DEFAULT 0,
    special_rate FLOAT,
    status VARCHAR(20) DEFAULT 'active',
    flexible_days BOOLEAN DEFAULT 0,
    requested_by_customer BOOLEAN DEFAULT 0,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS daycare_attendance (
    id INTEGER NOT NULL PRIMARY KEY,
    enrollment_id INTEGER NOT NULL REFERENCES daycare_enrollment (id),
    check_in_time DATETIME NOT NULL,
    check_out_time DATETIME,
    notes TEXT,
    play_group_id INTEGER REFERENCES play_group (id),
    payment_id INTEGER REFERENCES payment (id),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS daycare_waitlist (
    id INTEGER NOT NULL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    pet_name VARCHAR(100) DEFAULT '',
    breed VARCHAR(100),
    monday BOOLEAN DEFAULT 0,
    tuesday BOOLEAN DEFAULT 0,
    wednesday BOOLEAN DEFAULT 0,
    thursday BOOLEAN DEFAULT 0,
    friday BOOLEAN DEFAULT 0,
    additional_info TEXT,
    submitted_date DATETIME NOT NULL,
    contacted BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS boarding (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    user_id INTEGER NOT NULL REFERENCES user (id),
    check_in_date DATE NOT NULL,
    check_in_time VARCHAR(5) NOT NULL,
    check_out_date DATE NOT NULL,
    check_out_time VARCHAR(5) NOT NULL,
    medications TEXT,
    feeding_schedule TEXT,
    special_notes TEXT,
    kennel_number VARCHAR(20),
    kennel_type VARCHAR(10),
    checked_in BOOLEAN DEFAULT 0,
    checked_in_at DATETIME,
    emergency_contact VARCHAR(100),
    emergency_phone VARCHAR(20),
    feeding_amount VARCHAR(100),
    feeding_times VARCHAR(200),
    behavioral_flags TEXT,
    intake_complete BOOLEAN DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    created_at DATETIME,
    completed_at DATETIME,
    payment_id INTEGER REFERENCES payment (id)
);

CREATE TABLE IF NOT EXISTS kennel_status (
    kennel_number VARCHAR(20) NOT NULL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'clean',
    updated_at DATETIME,
    updated_by INTEGER REFERENCES user (id)
);

CREATE TABLE IF NOT EXISTS vaccination_record (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    vaccine_name VARCHAR(100) NOT NULL,
    vaccination_date DATE NOT NULL,
    expiration_date DATE NOT NULL,
    veterinarian VARCHAR(100),
    clinic_name VARCHAR(200),
    lot_number VARCHAR(50),
    notes TEXT,
    document_path VARCHAR(255),
    import_batch_id INTEGER REFERENCES import_batch (id),
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_vaccination_record_import_batch_id ON vaccination_record (import_batch_id);

CREATE TABLE IF NOT EXISTS health_check (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    check_date DATE NOT NULL,
    check_time DATETIME NOT NULL,
    checked_by VARCHAR(100) NOT NULL,
    appetite VARCHAR(20),
    energy_level VARCHAR(20),
    behavior VARCHAR(20),
    bathroom_normal BOOLEAN DEFAULT 1,
    temperature NUMERIC(4, 1),
    symptoms TEXT,
    treatment_given TEXT,
    notes TEXT,
    requires_attention BOOLEAN DEFAULT 0,
    owner_notified BOOLEAN DEFAULT 0,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS incident_log (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER REFERENCES pet (id),
    incident_date DATE NOT NULL,
    incident_time DATETIME NOT NULL,
    incident_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    description TEXT NOT NULL,
    location VARCHAR(100),
    witnesses TEXT,
    action_taken TEXT NOT NULL,
    reported_by VARCHAR(100) NOT NULL,
    owner_notified BOOLEAN DEFAULT 0,
    owner_notification_time DATETIME,
    vet_contacted BOOLEAN DEFAULT 0,
    vet_visit_required BOOLEAN DEFAULT 0,
    resolution TEXT,
    resolved BOOLEAN DEFAULT 0,
    resolved_date DATE,
    photos_taken BOOLEAN DEFAULT 0,
    photo_paths TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS capacity_log (
    id INTEGER NOT NULL PRIMARY KEY,
    log_date DATE NOT NULL UNIQUE,
    daycare_count INTEGER DEFAULT 0,
    boarding_count INTEGER DEFAULT 0,
    grooming_count INTEGER DEFAULT 0,
    total_count INTEGER DEFAULT 0,
    daycare_limit INTEGER DEFAULT 30,
    boarding_limit INTEGER DEFAULT 20,
    total_limit INTEGER DEFAULT 50,
    over_capacity BOOLEAN DEFAULT 0,
    notes TEXT,
    recorded_at DATETIME
);

CREATE TABLE IF NOT EXISTS invoice_adjustment (
    id INTEGER NOT NULL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES user (id),
    adj_type VARCHAR(20) NOT NULL DEFAULT 'custom',
    line_key VARCHAR(100),
    service_type VARCHAR(20) DEFAULT 'boarding',
    description VARCHAR(200) NOT NULL,
    amount FLOAT NOT NULL,
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS invoice_token (
    id INTEGER NOT NULL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES user (id),
    token VARCHAR(64) NOT NULL UNIQUE,
    created_at DATETIME,
    last_sent DATETIME
);

CREATE INDEX IF NOT EXISTS ix_invoice_token_token ON invoice_token (token);

CREATE TABLE IF NOT EXISTS sms_message (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER REFERENCES user (id),
    direction VARCHAR(10) NOT NULL,
    from_number VARCHAR(20),
    to_number VARCHAR(20),
    body TEXT,
    twilio_sid VARCHAR(40),
    is_read BOOLEAN DEFAULT 0,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS gallery_photo (
    id INTEGER NOT NULL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    caption VARCHAR(200),
    category VARCHAR(50) DEFAULT 'General',
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS report_card (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    card_type VARCHAR(10) NOT NULL,
    card_date DATE NOT NULL,
    token VARCHAR(64) NOT NULL UNIQUE,
    mood VARCHAR(20),
    energy VARCHAR(20),
    played_well VARCHAR(20),
    hydrated BOOLEAN,
    notes TEXT,
    photo_filename VARCHAR(255),
    appetite VARCHAR(20),
    sleep VARCHAR(20),
    temperament VARCHAR(20),
    medications_given BOOLEAN,
    bathroom VARCHAR(20),
    sent_at DATETIME,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS knowledge_article (
    id INTEGER NOT NULL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    pinned BOOLEAN DEFAULT 0,
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS password_reset_token (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    token VARCHAR(64) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    used BOOLEAN DEFAULT 0,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS magic_link_token (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    token VARCHAR(64) NOT NULL UNIQUE,
    expires_at DATETIME NOT NULL,
    used BOOLEAN DEFAULT 0,
    created_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_magic_link_token_user_id ON magic_link_token (user_id);
CREATE INDEX IF NOT EXISTS ix_magic_link_token_token ON magic_link_token (token);

CREATE TABLE IF NOT EXISTS survey_response (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    token VARCHAR(64) NOT NULL UNIQUE,
    service_type VARCHAR(50),
    trigger VARCHAR(50),
    overall_rating INTEGER,
    comm_rating INTEGER,
    recommend VARCHAR(10),
    comments TEXT,
    submitted_at DATETIME,
    sent_at DATETIME,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS staff_notice (
    id INTEGER NOT NULL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    priority VARCHAR(10) DEFAULT 'normal',
    action_url VARCHAR(500),
    expires_at DATETIME NOT NULL,
    created_by INTEGER REFERENCES user (id),
    dismissed_by TEXT,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS support_ticket (
    id INTEGER NOT NULL PRIMARY KEY,
    ticket_type VARCHAR(50) NOT NULL,
    subject VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'open',
    submitted_by INTEGER REFERENCES user (id),
    jira_issue_key VARCHAR(50),
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS ticket_comment (
    id INTEGER NOT NULL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES support_ticket (id),
    user_id INTEGER REFERENCES user (id),
    body TEXT NOT NULL,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS incident (
    id INTEGER NOT NULL PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    reported_by INTEGER REFERENCES user (id),
    incident_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    description TEXT NOT NULL,
    action_taken TEXT,
    owner_notified BOOLEAN DEFAULT 0,
    status VARCHAR(20) DEFAULT 'open',
    incident_date DATETIME NOT NULL,
    resolved_at DATETIME,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS customer_photo (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    filename VARCHAR(255) NOT NULL,
    caption VARCHAR(255),
    uploaded_by INTEGER REFERENCES user (id),
    uploaded_at DATETIME
);

CREATE TABLE IF NOT EXISTS daily_log (
    id INTEGER NOT NULL PRIMARY KEY,
    log_date DATE NOT NULL,
    author_id INTEGER NOT NULL REFERENCES user (id),
    notes TEXT,
    incidents TEXT,
    staffing TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_daily_log_log_date ON daily_log (log_date);

CREATE TABLE IF NOT EXISTS daily_log_pet_flag (
    id INTEGER NOT NULL PRIMARY KEY,
    log_id INTEGER NOT NULL REFERENCES daily_log (id),
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    flag_type VARCHAR(50),
    note VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS business_settings (
    id INTEGER NOT NULL PRIMARY KEY,
    sms_boarding_confirm BOOLEAN DEFAULT 1,
    sms_checkout_estimate BOOLEAN DEFAULT 1,
    sms_invoice_sent BOOLEAN DEFAULT 1,
    sms_no_pet_followup BOOLEAN DEFAULT 1,
    sms_no_vaccine_followup BOOLEAN DEFAULT 1,
    sms_vacc_expiry_staff BOOLEAN DEFAULT 1,
    sms_vacc_expiry_customer BOOLEAN DEFAULT 1,
    sms_daycare_checkin BOOLEAN DEFAULT 0,
    sms_daycare_checkout BOOLEAN DEFAULT 0,
    sms_reply_forward BOOLEAN DEFAULT 0,
    allow_self_registration BOOLEAN DEFAULT 1,
    require_waiver BOOLEAN DEFAULT 1,
    enforce_vaccinations BOOLEAN DEFAULT 1,
    allow_vacc_upload BOOLEAN DEFAULT 1,
    show_customer_gallery BOOLEAN DEFAULT 1,
    show_faq BOOLEAN DEFAULT 1,
    module_daycare BOOLEAN DEFAULT 1,
    module_grooming BOOLEAN DEFAULT 1,
    module_report_cards BOOLEAN DEFAULT 1,
    module_play_groups BOOLEAN DEFAULT 1,
    module_kiosk BOOLEAN DEFAULT 1,
    module_ai_chat BOOLEAN DEFAULT 1,
    module_daily_log BOOLEAN DEFAULT 1,
    low_capacity_alert BOOLEAN DEFAULT 1,
    low_capacity_threshold INTEGER DEFAULT 80,
    outstanding_balance_alert BOOLEAN DEFAULT 1,
    promotions_enabled BOOLEAN DEFAULT 0,
    twilio_account_sid VARCHAR(50),
    twilio_auth_token VARCHAR(50),
    twilio_phone_number VARCHAR(20),
    email_host VARCHAR(200),
    email_port INTEGER,
    email_use_tls BOOLEAN DEFAULT 1,
    email_username VARCHAR(200),
    email_password VARCHAR(200),
    email_from_name VARCHAR(200),
    google_review_url VARCHAR(300),
    sms_review_request BOOLEAN DEFAULT 1,
    total_kennels INTEGER DEFAULT 20,
    waitlist_autofill_enabled BOOLEAN DEFAULT 1,
    waitlist_confirm_hours INTEGER DEFAULT 2,
    surge_pricing_enabled BOOLEAN DEFAULT 0,
    post_stay_summary_enabled BOOLEAN DEFAULT 1,
    tier VARCHAR(20) NOT NULL DEFAULT 'pro',
    stripe_customer_id VARCHAR(100),
    stripe_subscription_id VARCHAR(100),
    stripe_subscription_status VARCHAR(20),
    multi_pet_discount_enabled BOOLEAN DEFAULT 0,
    multi_pet_full_price_count INTEGER DEFAULT 1,
    multi_pet_discount_type VARCHAR(10) DEFAULT 'percent',
    multi_pet_discount_value FLOAT,
    timezone VARCHAR(50) NOT NULL DEFAULT 'America/New_York',
    updated_at DATETIME,
    updated_by INTEGER REFERENCES user (id)
);

CREATE TABLE IF NOT EXISTS surge_pricing_rule (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    rule_type VARCHAR(20) NOT NULL DEFAULT 'date_range',
    start_date DATE,
    end_date DATE,
    occupancy_threshold INTEGER,
    multiplier NUMERIC(6, 4),
    flat_add NUMERIC(8, 2),
    flat_rate NUMERIC(8, 2),
    applies_to VARCHAR(100) NOT NULL DEFAULT 'boarding',
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    notes TEXT,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS med_round (
    id INTEGER NOT NULL PRIMARY KEY,
    boarding_id INTEGER NOT NULL REFERENCES boarding (id),
    round_name VARCHAR(20) NOT NULL,
    round_date DATE NOT NULL,
    administered_by INTEGER REFERENCES user (id),
    administered_at DATETIME,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS promotion_config (
    id INTEGER NOT NULL PRIMARY KEY,
    promo_codes_enabled BOOLEAN DEFAULT 1,
    punch_card_boarding_enabled BOOLEAN DEFAULT 1,
    punch_card_boarding_threshold INTEGER DEFAULT 10,
    punch_card_boarding_reward VARCHAR(200),
    punch_card_boarding_reward_amount NUMERIC(10, 2),
    punch_card_daycare_enabled BOOLEAN DEFAULT 1,
    punch_card_daycare_threshold INTEGER DEFAULT 20,
    punch_card_daycare_reward VARCHAR(200),
    punch_card_daycare_reward_amount NUMERIC(10, 2),
    punch_card_notify_sms BOOLEAN DEFAULT 1,
    punch_card_notify_email BOOLEAN DEFAULT 1,
    packages_enabled BOOLEAN DEFAULT 1,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS promo_code (
    id INTEGER NOT NULL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    description VARCHAR(200),
    discount_type VARCHAR(10) NOT NULL,
    discount_value NUMERIC(10, 2) NOT NULL,
    active BOOLEAN DEFAULT 1,
    expires_at DATETIME,
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS promo_code_use (
    id INTEGER NOT NULL PRIMARY KEY,
    promo_code_id INTEGER NOT NULL REFERENCES promo_code (id),
    customer_id INTEGER NOT NULL REFERENCES user (id),
    used_at DATETIME,
    invoice_adj_id INTEGER
);

CREATE TABLE IF NOT EXISTS loyalty_credit (
    id INTEGER NOT NULL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES user (id),
    credit_type VARCHAR(20) NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    description VARCHAR(200),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    earned_at DATETIME,
    applied_at DATETIME,
    applied_by INTEGER REFERENCES user (id),
    invoice_adj_id INTEGER
);

CREATE TABLE IF NOT EXISTS service_package (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    service_type VARCHAR(20) NOT NULL,
    unit_count INTEGER NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    description VARCHAR(300),
    expiry_days INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS customer_package (
    id INTEGER NOT NULL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES user (id),
    package_id INTEGER NOT NULL REFERENCES service_package (id),
    units_purchased INTEGER NOT NULL,
    units_remaining INTEGER NOT NULL,
    purchased_at DATETIME NOT NULL,
    expires_at DATETIME,
    notes VARCHAR(300),
    sold_by INTEGER REFERENCES user (id)
);

CREATE INDEX IF NOT EXISTS ix_customer_package_customer_id ON customer_package (customer_id);

CREATE TABLE IF NOT EXISTS boarding_waitlist (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES user (id),
    pet_id INTEGER NOT NULL REFERENCES pet (id),
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    notes TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'waiting',
    notified_at DATETIME,
    expires_at DATETIME,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS marketing_campaign (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    goal TEXT,
    start_date DATE,
    end_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS marketing_post (
    id INTEGER NOT NULL PRIMARY KEY,
    campaign_id INTEGER REFERENCES marketing_campaign (id),
    title VARCHAR(120) NOT NULL,
    platform VARCHAR(30) NOT NULL,
    copy TEXT,
    scheduled_date DATE,
    scheduled_time TIME,
    category VARCHAR(60),
    post_format VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    notes TEXT,
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS drp_sequence (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    trigger_type VARCHAR(50) NOT NULL,
    trigger_days INTEGER,
    holiday_key VARCHAR(50),
    channel VARCHAR(20) NOT NULL DEFAULT 'sms',
    message_template TEXT NOT NULL,
    active BOOLEAN DEFAULT 1,
    created_at DATETIME
);

CREATE TABLE IF NOT EXISTS drp_enrollment (
    id INTEGER NOT NULL PRIMARY KEY,
    sequence_id INTEGER NOT NULL REFERENCES drp_sequence (id),
    user_id INTEGER NOT NULL REFERENCES user (id),
    enrolled_at DATETIME,
    next_send_date DATETIME,
    last_sent_at DATETIME,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    send_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS saved_reports (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    description VARCHAR(255),
    source VARCHAR(50) NOT NULL DEFAULT 'boarding',
    config_json TEXT NOT NULL DEFAULT '{}',
    created_by INTEGER REFERENCES user (id),
    created_at DATETIME,
    updated_at DATETIME,
    last_run_at DATETIME,
    run_count INTEGER DEFAULT 0
);
