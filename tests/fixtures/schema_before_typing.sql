CREATE TABLE web_users (
	id SERIAL NOT NULL,
	username VARCHAR NOT NULL,
	password_hash VARCHAR NOT NULL,
	display_name VARCHAR,
	telegram_username VARCHAR,
	telegram_chat_id VARCHAR,
	is_admin BOOLEAN,
	is_active BOOLEAN,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id)
)


CREATE INDEX ix_web_users_id ON web_users (id)
CREATE UNIQUE INDEX ix_web_users_username ON web_users (username)

CREATE TABLE tracked_routes (
	id SERIAL NOT NULL,
	title VARCHAR,
	telegram_chat_id VARCHAR,
	notification_mode VARCHAR,
	notification_username VARCHAR,
	web_user_id INTEGER,
	creator_source VARCHAR,
	creator_display_name VARCHAR,
	creator_username VARCHAR,
	creator_telegram_user_id VARCHAR,
	origin VARCHAR(3) NOT NULL,
	destination VARCHAR(3) NOT NULL,
	departure_date VARCHAR NOT NULL,
	return_date VARCHAR,
	trip_type VARCHAR,
	adult_seats INTEGER,
	children_seats INTEGER,
	infant_seats INTEGER,
	baggage_required BOOLEAN,
	max_price FLOAT NOT NULL,
	interval_minutes INTEGER,
	direct_only BOOLEAN,
	airline_codes VARCHAR,
	origin_airports VARCHAR,
	destination_airports VARCHAR,
	departure_time_from VARCHAR,
	departure_time_to VARCHAR,
	arrival_time_from VARCHAR,
	arrival_time_to VARCHAR,
	return_departure_time_from VARCHAR,
	return_departure_time_to VARCHAR,
	return_arrival_time_from VARCHAR,
	return_arrival_time_to VARCHAR,
	no_change_checks_count INTEGER,
	is_active BOOLEAN,
	last_best_price FLOAT,
	last_checked_at TIMESTAMP WITHOUT TIME ZONE,
	last_error TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(web_user_id) REFERENCES web_users (id)
)


CREATE INDEX ix_tracked_routes_id ON tracked_routes (id)

CREATE TABLE price_checks (
	id SERIAL NOT NULL,
	tracked_route_id INTEGER NOT NULL,
	checked_at TIMESTAMP WITHOUT TIME ZONE,
	price FLOAT NOT NULL,
	matches_filters BOOLEAN,
	airline VARCHAR,
	flight_number VARCHAR,
	gate VARCHAR,
	origin VARCHAR(3),
	destination VARCHAR(3),
	origin_airport VARCHAR(3),
	destination_airport VARCHAR(3),
	departure_at TIMESTAMP WITHOUT TIME ZONE,
	duration INTEGER,
	estimated_arrival_at TIMESTAMP WITHOUT TIME ZONE,
	is_estimated_arrival BOOLEAN,
	transfers INTEGER,
	link TEXT,
	aviasales_url TEXT,
	yandex_travel_url TEXT,
	raw_json TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(tracked_route_id) REFERENCES tracked_routes (id)
)


CREATE INDEX ix_price_checks_id ON price_checks (id)

CREATE TABLE notifications (
	id SERIAL NOT NULL,
	tracked_route_id INTEGER NOT NULL,
	price_check_id INTEGER,
	sent_at TIMESTAMP WITHOUT TIME ZONE,
	channel VARCHAR,
	message TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(tracked_route_id) REFERENCES tracked_routes (id),
	FOREIGN KEY(price_check_id) REFERENCES price_checks (id)
)


CREATE INDEX ix_notifications_id ON notifications (id)
