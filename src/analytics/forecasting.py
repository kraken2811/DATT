"""Tomorrow Traffic Forecasting Engine for DATT.

Implements explainable statistical baseline:
Weighted Same-Weekday Historical Forecasting with Rolling-Origin Backtesting.
Computes expected hourly traffic, prediction intervals, and peak periods.
Strictly respects data quality gates: READY, LIMITED_DATA, INSUFFICIENT_DATA, STALE_DATA, ERROR.
"""

from datetime import datetime, date, timezone, timedelta
import math
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, and_

from src.db.database import Database
from src.db.models import CrossingEvent, AnalyticsAggregate, TrafficForecast, Camera
from src.db.repositories.analytics_repository import TrafficForecastRepository

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)
MIN_HISTORICAL_DAYS_FOR_READY = 3
MAX_LOOKBACK_WEEKS = 8


def get_tomorrow_date_local() -> tuple[str, int, datetime]:
    """Return tomorrow's date string YYYY-MM-DD, weekday index (0..6), and datetime in ICT."""
    now_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ)
    tomorrow_local = now_local + timedelta(days=1)
    d_str = tomorrow_local.strftime("%Y-%m-%d")
    w_idx = tomorrow_local.weekday()
    return d_str, w_idx, tomorrow_local


class TomorrowForecastEngine:
    """Statistical forecasting engine for people and vehicle traffic."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self.model_version = "weighted_same_weekday_v1"

    def forecast_tomorrow(
        self,
        camera_id: str,
        target_date_str: str | None = None,
        zone_id: str | None = None,
        object_type: str | None = None,  # "person", "vehicle", or None (both)
        save_to_db: bool = True,
    ) -> dict[str, Any]:
        """Generate tomorrow traffic forecast for a given camera or zone."""
        if target_date_str:
            target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            target_date = target_date_str
            target_weekday = target_dt.weekday()
        else:
            target_date, target_weekday, target_dt = get_tomorrow_date_local()

        weekday_names = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        weekday_name = weekday_names[target_weekday]

        with self.db.transaction() as session:
            # 1. Identify previous matching weekdays within lookback window
            # e.g., if tomorrow is Friday, look back at previous Fridays (1 week ago, 2 weeks ago, ...)
            candidate_dates: list[tuple[date, int]] = []  # (date, weeks_ago)
            base_date = target_dt.date()
            for k in range(1, MAX_LOOKBACK_WEEKS + 1):
                past_date = base_date - timedelta(weeks=k)
                candidate_dates.append((past_date, k))

            # 2. Retrieve hourly traffic for each candidate date
            is_pg = session.bind.dialect.name == "postgresql"

            historical_day_data: list[dict[str, Any]] = []

            for past_date, weeks_ago in candidate_dates:
                p_start_local = datetime.combine(past_date, datetime.min.time(), tzinfo=LOCAL_TZ)
                p_end_local = datetime.combine(past_date, datetime.max.time(), tzinfo=LOCAL_TZ)
                p_start_utc = p_start_local.astimezone(timezone.utc)
                p_end_utc = p_end_local.astimezone(timezone.utc)

                filters = [
                    CrossingEvent.camera_id == camera_id,
                    CrossingEvent.event_time >= p_start_utc,
                    CrossingEvent.event_time <= p_end_utc,
                ]
                if zone_id:
                    filters.append(CrossingEvent.zone_id == zone_id)
                if object_type:
                    filters.append(CrossingEvent.object_type == object_type)

                if is_pg:
                    h_expr = func.extract("hour", func.timezone("Asia/Ho_Chi_Minh", CrossingEvent.event_time))
                else:
                    h_expr = func.strftime("%H", func.datetime(CrossingEvent.event_time, "+7 hours"))

                stmt = select(
                    h_expr,
                    CrossingEvent.object_type,
                    CrossingEvent.direction,
                    func.count(CrossingEvent.id).label("count")
                ).where(and_(*filters)).group_by(
                    h_expr, CrossingEvent.object_type, CrossingEvent.direction
                )

                rows = session.execute(stmt).all()
                day_total = sum(int(r[3]) for r in rows)

                # Skip days with zero traffic if other days have traffic (unless camera was active and idle)
                if day_total > 0:
                    hourly_counts = {
                        h: {
                            "total": 0,
                            "person_in": 0,
                            "person_out": 0,
                            "vehicle_in": 0,
                            "vehicle_out": 0,
                        }
                        for h in range(24)
                    }

                    for h_val, o_type, o_dir, cnt in rows:
                        if h_val is not None:
                            h_idx = int(h_val)
                            if 0 <= h_idx < 24:
                                c = int(cnt)
                                hourly_counts[h_idx]["total"] += c
                                if o_type == "person":
                                    if o_dir == "in":
                                        hourly_counts[h_idx]["person_in"] += c
                                    else:
                                        hourly_counts[h_idx]["person_out"] += c
                                elif o_type == "vehicle":
                                    if o_dir == "in":
                                        hourly_counts[h_idx]["vehicle_in"] += c
                                    else:
                                        hourly_counts[h_idx]["vehicle_out"] += c

                    historical_day_data.append({
                        "date": past_date.isoformat(),
                        "weeks_ago": weeks_ago,
                        "weight": round(math.pow(0.85, weeks_ago - 1), 3),
                        "total": day_total,
                        "hourly": hourly_counts,
                    })

            # 3. Determine data quality status
            num_days_used = len(historical_day_data)
            if num_days_used == 0:
                quality_status = "INSUFFICIENT_DATA"
                message = "Chưa đủ dữ liệu lịch sử đáng tin cậy để dự báo lưu lượng ngày mai."
                return {
                    "status": "warning",
                    "camera_id": camera_id,
                    "target_date": target_date,
                    "target_weekday": target_weekday,
                    "weekday_name": weekday_name,
                    "data_quality_status": quality_status,
                    "message": message,
                    "historical_days_used": 0,
                    "hourly_forecasts": [],
                    "peak_hours": [],
                    "total_forecast": {"expected": 0, "lower_bound_80": 0, "upper_bound_80": 0},
                    "backtest_metrics": None,
                }
            elif num_days_used >= MIN_HISTORICAL_DAYS_FOR_READY:
                # Check staleness: most recent observation should not be > 21 days old
                min_weeks = min(d["weeks_ago"] for d in historical_day_data)
                if min_weeks > 3:
                    quality_status = "STALE_DATA"
                else:
                    quality_status = "READY"
            else:
                quality_status = "LIMITED_DATA"

            # 4. Compute Weighted Hourly Expectation & Prediction Intervals
            total_weight = sum(d["weight"] for d in historical_day_data)
            hourly_forecasts = []
            sum_expected_total = 0
            sum_lower_80 = 0
            sum_upper_80 = 0

            for h in range(24):
                # Weighted average for total, person_in, person_out, vehicle_in, vehicle_out
                w_sum_total = sum(d["weight"] * d["hourly"][h]["total"] for d in historical_day_data)
                w_sum_pin = sum(d["weight"] * d["hourly"][h]["person_in"] for d in historical_day_data)
                w_sum_pout = sum(d["weight"] * d["hourly"][h]["person_out"] for d in historical_day_data)
                w_sum_vin = sum(d["weight"] * d["hourly"][h]["vehicle_in"] for d in historical_day_data)
                w_sum_vout = sum(d["weight"] * d["hourly"][h]["vehicle_out"] for d in historical_day_data)

                exp_total = w_sum_total / total_weight
                exp_pin = round(w_sum_pin / total_weight, 1)
                exp_pout = round(w_sum_pout / total_weight, 1)
                exp_vin = round(w_sum_vin / total_weight, 1)
                exp_vout = round(w_sum_vout / total_weight, 1)

                # Variance & standard deviation
                w_variance = sum(
                    d["weight"] * math.pow(d["hourly"][h]["total"] - exp_total, 2)
                    for d in historical_day_data
                ) / total_weight
                std_dev = math.sqrt(w_variance)

                # Prediction intervals
                # 80% interval (z = 1.28)
                lower_80 = max(0, int(round(exp_total - 1.28 * std_dev)))
                upper_80 = int(round(exp_total + 1.28 * std_dev))
                # 95% interval (z = 1.96)
                lower_95 = max(0, int(round(exp_total - 1.96 * std_dev)))
                upper_95 = int(round(exp_total + 1.96 * std_dev))

                round_exp = int(round(exp_total))
                sum_expected_total += round_exp
                sum_lower_80 += lower_80
                sum_upper_80 += upper_80

                hourly_forecasts.append({
                    "hour": h,
                    "hour_slot": f"{h:02d}:00 - {h+1:02d}:00",
                    "expected_passages": round_exp,
                    "prediction_interval_80": {"lower": lower_80, "upper": upper_80},
                    "prediction_interval_95": {"lower": lower_95, "upper": upper_95},
                    "std_deviation": round(std_dev, 1),
                    "person_in": exp_pin,
                    "person_out": exp_pout,
                    "vehicle_in": exp_vin,
                    "vehicle_out": exp_vout,
                })

            # 5. Peak Period Identification
            # Find top 3 hours with highest expected traffic
            sorted_by_traffic = sorted(hourly_forecasts, key=lambda x: x["expected_passages"], reverse=True)
            peak_hours = []
            if sorted_by_traffic and sorted_by_traffic[0]["expected_passages"] > 0:
                top_traffic = sorted_by_traffic[0]["expected_passages"]
                threshold = max(5, int(top_traffic * 0.70))
                for item in sorted_by_traffic[:4]:
                    if item["expected_passages"] >= threshold:
                        peak_hours.append({
                            "hour": item["hour"],
                            "hour_slot": item["hour_slot"],
                            "expected_passages": item["expected_passages"],
                            "range_80": f"{item['prediction_interval_80']['lower']} - {item['prediction_interval_80']['upper']}",
                        })
                # Re-sort peak hours chronologically
                peak_hours = sorted(peak_hours, key=lambda x: x["hour"])

            # 6. Backtesting (Rolling-Origin Evaluation without future leakage)
            backtest_metrics = None
            if num_days_used >= 2:
                # Test on the most recent historical day using older days as training
                test_day = historical_day_data[0]  # most recent (lowest weeks_ago)
                train_days = historical_day_data[1:]  # strictly older

                w_train_total = sum(d["weight"] for d in train_days)
                abs_errors = []
                sq_errors = []
                covered_80 = 0
                actual_sum = 0

                for h in range(24):
                    actual_val = test_day["hourly"][h]["total"]
                    actual_sum += actual_val

                    pred_val = sum(d["weight"] * d["hourly"][h]["total"] for d in train_days) / w_train_total
                    var = sum(d["weight"] * math.pow(d["hourly"][h]["total"] - pred_val, 2) for d in train_days) / w_train_total
                    s_dev = math.sqrt(var)

                    err = abs(actual_val - pred_val)
                    abs_errors.append(err)
                    sq_errors.append(err * err)

                    l_80 = max(0, pred_val - 1.28 * s_dev)
                    u_80 = pred_val + 1.28 * s_dev
                    if l_80 <= actual_val <= u_80:
                        covered_80 += 1

                mae = round(sum(abs_errors) / 24.0, 1)
                rmse = round(math.sqrt(sum(sq_errors) / 24.0), 1)
                wape = round((sum(abs_errors) / max(1.0, actual_sum)) * 100.0, 1)
                coverage_pct = round((covered_80 / 24.0) * 100.0, 1)

                backtest_metrics = {
                    "evaluation_method": "rolling_origin_chronological",
                    "test_date": test_day["date"],
                    "mae": mae,
                    "wape_percent": wape,
                    "rmse": rmse,
                    "interval_coverage_80_percent": coverage_pct,
                }

            result = {
                "status": "success",
                "camera_id": camera_id,
                "target_date": target_date,
                "target_weekday": target_weekday,
                "weekday_name": weekday_name,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model_version": self.model_version,
                "data_quality_status": quality_status,
                "historical_days_used": num_days_used,
                "historical_dates": [d["date"] for d in historical_day_data],
                "total_forecast": {
                    "expected": sum_expected_total,
                    "lower_bound_80": sum_lower_80,
                    "upper_bound_80": sum_upper_80,
                },
                "peak_hours": peak_hours,
                "hourly_forecasts": hourly_forecasts,
                "backtest_metrics": backtest_metrics,
            }

            # 7. Persist to database if requested
            if save_to_db:
                repo = TrafficForecastRepository(session)
                repo.save_forecast(
                    camera_id=camera_id,
                    target_date=target_date,
                    target_weekday=target_weekday,
                    zone_id=zone_id,
                    model_version=self.model_version,
                    data_quality_status=quality_status,
                    hourly_forecasts=hourly_forecasts,
                    peak_hours=peak_hours,
                    total_forecast_traffic=result["total_forecast"],
                    historical_days_used=num_days_used,
                    backtest_metrics=backtest_metrics or {},
                    notes=f"Forecast for {weekday_name} ({target_date}) based on {num_days_used} past {weekday_name}s",
                )

            return result
