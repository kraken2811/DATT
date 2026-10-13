"""Historical analytics, crossing events, and tomorrow forecasting tables.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    # 1. crossing_events
    op.create_table(
        'crossing_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('camera_id', sa.String(255), nullable=False),
        sa.Column('zone_id', sa.String(100), nullable=True),
        sa.Column('object_type', sa.String(50), nullable=False),
        sa.Column('object_class', sa.String(50), nullable=False, server_default='person'),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('tracking_session_id', sa.String(255), nullable=False),
        sa.Column('event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False, server_default='live'),
        sa.Column('video_source_id', sa.Uuid(), sa.ForeignKey('video_sources.id', ondelete='SET NULL'), nullable=True),
        sa.Column('idempotency_key', sa.String(255), nullable=False),
        sa.Column('metadata', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_crossing_events_camera_id', 'crossing_events', ['camera_id'])
    op.create_index('ix_crossing_events_zone_id', 'crossing_events', ['zone_id'])
    op.create_index('ix_crossing_events_object_type', 'crossing_events', ['object_type'])
    op.create_index('ix_crossing_events_direction', 'crossing_events', ['direction'])
    op.create_index('ix_crossing_events_track_id', 'crossing_events', ['track_id'])
    op.create_index('ix_crossing_events_tracking_session_id', 'crossing_events', ['tracking_session_id'])
    op.create_index('ix_crossing_events_event_time', 'crossing_events', ['event_time'])
    op.create_index('ix_crossing_events_video_source_id', 'crossing_events', ['video_source_id'])
    op.create_index('ix_crossing_events_idempotency_key', 'crossing_events', ['idempotency_key'], unique=True)
    op.create_index('ix_crossing_events_cam_time', 'crossing_events', ['camera_id', 'event_time'])
    op.create_index('ix_crossing_events_type_time', 'crossing_events', ['object_type', 'event_time'])
    op.create_index('ix_crossing_events_zone_time', 'crossing_events', ['zone_id', 'event_time'])

    # 2. analytics_aggregates
    op.create_table(
        'analytics_aggregates',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('camera_id', sa.String(255), nullable=False),
        sa.Column('zone_id', sa.String(100), nullable=True),
        sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('bucket_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='Asia/Ho_Chi_Minh'),
        sa.Column('bucket_duration_minutes', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('person_in_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('person_out_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vehicle_in_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vehicle_out_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vehicle_type_breakdown', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('average_visible_person_count', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('maximum_visible_person_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('average_visible_vehicle_count', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('maximum_visible_vehicle_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('observed_seconds', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('expected_seconds', sa.Float(), nullable=False, server_default='900.0'),
        sa.Column('coverage_ratio', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('data_quality_status', sa.String(50), nullable=False, server_default='EXCELLENT'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('camera_id', 'zone_id', 'bucket_start', name='uq_analytics_aggregates_cam_zone_bucket'),
    )
    op.create_index('ix_analytics_aggregates_camera_id', 'analytics_aggregates', ['camera_id'])
    op.create_index('ix_analytics_aggregates_zone_id', 'analytics_aggregates', ['zone_id'])
    op.create_index('ix_analytics_aggregates_bucket_start', 'analytics_aggregates', ['bucket_start'])
    op.create_index('ix_analytics_aggregates_bucket_end', 'analytics_aggregates', ['bucket_end'])
    op.create_index('ix_analytics_aggregates_cam_start', 'analytics_aggregates', ['camera_id', 'bucket_start'])

    # 3. camera_analytics_configs
    op.create_table(
        'camera_analytics_configs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('camera_id', sa.String(255), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('counting_line', JSON_TYPE, nullable=True),
        sa.Column('in_direction', sa.String(50), nullable=False, server_default='normal'),
        sa.Column('roi_polygon', JSON_TYPE, nullable=True),
        sa.Column('supported_classes', JSON_TYPE, nullable=False, server_default='["person", "car", "motorcycle", "bus", "truck"]'),
        sa.Column('min_crossing_distance', sa.Float(), nullable=False, server_default='0.015'),
        sa.Column('hysteresis_frames', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('capacity', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_camera_analytics_configs_camera_id', 'camera_analytics_configs', ['camera_id'], unique=True)

    # 4. traffic_forecasts
    op.create_table(
        'traffic_forecasts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('camera_id', sa.String(255), nullable=False),
        sa.Column('zone_id', sa.String(100), nullable=True),
        sa.Column('target_date', sa.String(20), nullable=False),
        sa.Column('target_weekday', sa.Integer(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('model_version', sa.String(50), nullable=False, server_default='weighted_same_weekday_v1'),
        sa.Column('data_quality_status', sa.String(50), nullable=False, server_default='READY'),
        sa.Column('hourly_forecasts', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('peak_hours', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('total_forecast_traffic', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('historical_days_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('backtest_metrics', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('camera_id', 'zone_id', 'target_date', name='uq_traffic_forecasts_cam_zone_date'),
    )
    op.create_index('ix_traffic_forecasts_camera_id', 'traffic_forecasts', ['camera_id'])
    op.create_index('ix_traffic_forecasts_zone_id', 'traffic_forecasts', ['zone_id'])
    op.create_index('ix_traffic_forecasts_target_date', 'traffic_forecasts', ['target_date'])
    op.create_index('ix_traffic_forecasts_cam_date', 'traffic_forecasts', ['camera_id', 'target_date'])

    # 5. forecast_alert_rules
    op.create_table(
        'forecast_alert_rules',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('camera_id', sa.String(255), nullable=True),
        sa.Column('zone_id', sa.String(100), nullable=True),
        sa.Column('alert_type', sa.String(50), nullable=False, server_default='EXPECTED_HIGH_TRAFFIC'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('high_traffic_threshold', sa.Integer(), nullable=False, server_default='200'),
        sa.Column('peak_traffic_threshold', sa.Integer(), nullable=False, server_default='500'),
        sa.Column('capacity_threshold_ratio', sa.Float(), nullable=False, server_default='0.85'),
        sa.Column('min_coverage_ratio', sa.Float(), nullable=False, server_default='0.70'),
        sa.Column('recipient_emails', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_forecast_alert_rules_camera_id', 'forecast_alert_rules', ['camera_id'])

    # 6. forecast_alerts
    op.create_table(
        'forecast_alerts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('forecast_id', sa.Uuid(), sa.ForeignKey('traffic_forecasts.id', ondelete='CASCADE'), nullable=True),
        sa.Column('camera_id', sa.String(255), nullable=False),
        sa.Column('zone_id', sa.String(100), nullable=True),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='HIGH'),
        sa.Column('target_date', sa.String(20), nullable=False),
        sa.Column('peak_window', sa.String(100), nullable=True),
        sa.Column('expected_traffic', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('threshold_value', sa.Float(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('delivery_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('recipient', sa.String(320), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_forecast_alerts_forecast_id', 'forecast_alerts', ['forecast_id'])
    op.create_index('ix_forecast_alerts_camera_id', 'forecast_alerts', ['camera_id'])
    op.create_index('ix_forecast_alerts_alert_type', 'forecast_alerts', ['alert_type'])
    op.create_index('ix_forecast_alerts_target_date', 'forecast_alerts', ['target_date'])
    op.create_index('ix_forecast_alerts_cam_date', 'forecast_alerts', ['camera_id', 'target_date'])
    op.create_index('ix_forecast_alerts_status', 'forecast_alerts', ['delivery_status'])


def downgrade():
    op.drop_table('forecast_alerts')
    op.drop_table('forecast_alert_rules')
    op.drop_table('traffic_forecasts')
    op.drop_table('camera_analytics_configs')
    op.drop_table('analytics_aggregates')
    op.drop_table('crossing_events')
