# ems_project/app.py

from flask import Flask, jsonify, render_template, request, redirect, url_for
import sqlite3
import pandas as pd
import datetime
import os
import json
import traceback
from datetime import datetime

def validate_date(date_str):
    if not date_str:
        return None
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except ValueError:
        return None
# from data_collector import init_db # 在生產環境中通常不從 web app 初始化

app = Flask(__name__, template_folder='templates', static_folder='static')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "url_manager.db"
DB_PATH = os.path.join(BASE_DIR, DB_NAME)
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- 頁面路由 ---
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/regression')
def regression_baseline():
    return render_template('regression.html')

@app.route('/admin')
def admin_config():
    return render_template('admin.html')


# --- Regression Baseline APIs ---
@app.route('/api/regression_baselines', methods=['GET', 'POST'])
def handle_regression_baselines():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            data = request.json
            cursor = conn.cursor()
            cursor.execute("INSERT INTO RegressionBaselines (name, year, formula_intercept, formula_r2, notes) VALUES (?, ?, ?, ?, ?)", (data['name'], data['year'], data['intercept'], data.get('r2'), data.get('notes')))
            baseline_id = cursor.lastrowid
            for factor in data['factors']: conn.execute("INSERT INTO RegressionFactors (baseline_id, factor_name, coefficient) VALUES (?, ?, ?)",(baseline_id, factor['name'], factor['coeff']))
            conn.commit()
            return jsonify({"success": True, "message": "迴歸基線已建立", "id": baseline_id}), 201
        else: # GET
            baselines = conn.execute("SELECT * FROM RegressionBaselines ORDER BY year DESC, name ASC").fetchall()
            return jsonify([dict(row) for row in baselines])
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "基線名稱已存在"}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()

@app.route('/api/regression_baselines/<int:id>', methods=['GET'])
def get_regression_baseline_details(id):
    conn = get_db_connection()
    try:
        baseline = conn.execute("SELECT * FROM RegressionBaselines WHERE id = ?", (id,)).fetchone()
        if not baseline: return jsonify({"error": "Baseline not found"}), 404
        factors = conn.execute("SELECT factor_name, coefficient FROM RegressionFactors WHERE baseline_id = ?", (id,)).fetchall()
        monitored_data = conn.execute("SELECT month, factors_json, actual_consumption FROM MonitoredData WHERE baseline_id = ?", (id,)).fetchall()
        monitored_dict = { m['month']: {"factors": json.loads(m['factors_json']) if m['factors_json'] else {}, "actual_consumption": m['actual_consumption']} for m in monitored_data }
        response = {"baseline": dict(baseline), "factors": [dict(f) for f in factors], "monitored_data": monitored_dict}
        return jsonify(response)
    finally:
        if conn: conn.close()

@app.route('/api/monitored_data', methods=['POST'])
def handle_monitored_data():
    conn = get_db_connection()
    try:
        data = request.json
        conn.execute("""
            INSERT INTO MonitoredData (baseline_id, month, factors_json, actual_consumption) VALUES (?, ?, ?, ?) 
            ON CONFLICT(baseline_id, month) DO UPDATE SET 
                factors_json = excluded.factors_json, 
                actual_consumption = excluded.actual_consumption
        """, (data['baseline_id'], data['month'], json.dumps(data['factors']), data.get('actual_consumption')))
        conn.commit()
        return jsonify({"success": True, "message": "監控數據已儲存"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()


# --- Dashboard Chart APIs ---
@app.route('/api/realtime_dashboard', methods=['GET'])
def get_realtime_dashboard_data():
    # ... (此函式內容保持不變，使用之前修正好的版本) ...
    conn = get_db_connection()
    dashboard_data = []
    try:
        charts_cursor = conn.execute("SELECT * FROM DashboardCharts ORDER BY display_order, id")
        for chart_row in charts_cursor.fetchall():
            chart_config = dict(chart_row)
            series_cursor = conn.execute("SELECT * FROM DashboardSeries WHERE chart_id = ?", (chart_config['id'],))
            series_configs = [dict(s) for s in series_cursor.fetchall()]
            if series_configs:
                time_col = chart_config['time_column']
                table_name = chart_config['source_table_name']
                time_grouping = chart_config.get('time_grouping', 'hour')
                if time_grouping == 'hour': sql_date_format, sql_group_by_format = "%Y-%m-%d", "strftime('%H', {time_col})"
                elif time_grouping == 'day': sql_date_format, sql_group_by_format = "%Y-%m", "strftime('%d', {time_col})"
                elif time_grouping == 'month': sql_date_format, sql_group_by_format = "%Y", "strftime('%m', {time_col})"
                else: sql_date_format, sql_group_by_format = "%Y-%m-%d", "strftime('%H', {time_col})"
                agg_clauses = []
                for s_config in series_configs:
                    method = s_config.get('aggregation_method')
                    agg_func = "SUM" if method and method.lower() == 'sum' else "AVG"
                    agg_clauses.append(f'{agg_func}("{s_config["source_column_name"]}") as "{s_config["source_column_name"]}"'
)
                agg_cols_str = ', '.join(agg_clauses)
                query = f"""
                    SELECT {sql_group_by_format.format(time_col=time_col)} as x_axis, {agg_cols_str} 
                    FROM "{table_name}"
                    WHERE strftime('{sql_date_format}', "{time_col}") = strftime('{sql_date_format}', 'now', 'localtime')
                    AND "{time_col}" IS NOT NULL
                    GROUP BY x_axis ORDER BY x_axis
                """
                df = pd.read_sql_query(query, conn)
                if not df.empty:
                    df = df.sort_values(by='x_axis')
                    chart_data = {'tableName': chart_config['chart_title'], 'labels': df['x_axis'].tolist(), 'datasets': []}
                    for s_config in series_configs:
                        col_name = s_config['source_column_name']
                        df[col_name] = pd.to_numeric(df[col_name], errors='coerce').fillna(0)
                        method = s_config.get('aggregation_method')
                        agg_label = "(累加)" if method and method.lower() == 'sum' else "(平均)"
                        series_label_with_agg = f"{s_config['series_label']} {agg_label}"
                        chart_data['datasets'].append({'label': series_label_with_agg, 'data': df[col_name].tolist(), 'type': s_config['chart_type'], 'yAxisID': s_config['y_axis_id']})
                    dashboard_data.append(chart_data)
    except Exception as e:
        print(f"產生儀表板數據時發生錯誤: {e}")
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()
    return jsonify(dashboard_data)




# ... (Dashboard Chart CRUD APIs 保持不變) ...

# --- 圖表管理設定 API ---

@app.route('/api/config/tables', methods=['GET'])
def get_available_tables():
    """回傳資料庫中所有可用的資料表名稱列表"""
    conn = get_db_connection()
    # 排除 SQLite 系統表和我們自己的設定表
    query = """
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'Dashboard%' 
        AND name NOT LIKE 'data_templates%' AND name NOT LIKE 'Regression%' AND name NOT LIKE 'Monitored%'
    """
    tables = [row['name'] for row in conn.execute(query).fetchall()]
    conn.close()
    return jsonify(tables)

@app.route('/api/config/columns', methods=['GET'])
def get_table_columns():
    """根據給定的資料表名稱，回傳其所有欄位名稱"""
    table_name = request.args.get('table')
    if not table_name:
        return jsonify({"error": "未提供資料表名稱"}), 400
    
    conn = get_db_connection()
    try:
        # 獲取所有合法的資料表名稱
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        valid_tables = [row['name'] for row in cursor.fetchall()]

        # 檢查請求的資料表名稱是否在合法列表中
        if table_name not in valid_tables:
            return jsonify({"error": "無效或不存在的資料表名稱"}), 400

        # 使用安全的 PRAGMA 查詢
        cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
        columns = [row['name'] for row in cursor.fetchall()]
        return jsonify(columns)
    except Exception as e:
        return jsonify({"error": f"無法讀取資料表 {table_name} 的資訊: {e}"}), 500
    finally:
        conn.close()

def _get_valid_table_and_columns(conn):
    valid_tables = {}
    query = """
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'Dashboard%' 
        AND name NOT LIKE 'data_templates%' AND name NOT LIKE 'Regression%' AND name NOT LIKE 'Monitored%'
    """
    tables = [row['name'] for row in conn.execute(query).fetchall()]
    
    for table_name in tables:
        try:
            cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
            columns = [row['name'] for row in cursor.fetchall()]
            valid_tables[table_name] = columns
        except Exception:
            pass # Ignore tables that can't be read for some reason
    return valid_tables

# 在 app.py 中，找到 handle_chart_configs 函式並替換
@app.route('/api/config/charts', methods=['GET', 'POST'])
def handle_chart_configs():
    """GET: 獲取所有圖表設定。POST: 新增一筆圖表設定。"""
    conn = get_db_connection()
    if request.method == 'POST':
        data = request.json
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO DashboardCharts (chart_title, source_table_name, time_column, time_grouping, display_order) VALUES (?, ?, ?, ?, ?)",
            (data['chart_title'], data['source_table_name'], data['time_column'], data['time_grouping'], data.get('display_order', 0))
        )
        chart_id = cursor.lastrowid
        for series in data['series']:
            cursor.execute(
                # *** 修改點：新增 aggregation_method ***
                "INSERT INTO DashboardSeries (chart_id, source_column_name, series_label, chart_type, y_axis_id, aggregation_method) VALUES (?, ?, ?, ?, ?, ?)",
                (chart_id, series['source_column_name'], series['series_label'], series['chart_type'], series['y_axis_id'], series['aggregation_method'])
            )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "圖表已建立", "id": chart_id}), 201

    else: # GET (保持不變，因為 `SELECT *` 會自動包含新欄位)
        charts_cursor = conn.execute("SELECT * FROM DashboardCharts ORDER BY display_order, id")
        charts = []
        for chart_row in charts_cursor.fetchall():
            chart_dict = dict(chart_row)
            series_cursor = conn.execute("SELECT * FROM DashboardSeries WHERE chart_id = ?", (chart_dict['id'],))
            chart_dict['series'] = [dict(s) for s in series_cursor.fetchall()]
            charts.append(chart_dict)
        conn.close()
        return jsonify(charts)
# 在 app.py 中，找到 handle_single_chart_config 函式並替換
@app.route('/api/config/charts/<int:chart_id>', methods=['PUT', 'DELETE'])
def handle_single_chart_config(chart_id):
    """PUT: 更新指定圖表設定。DELETE: 刪除指定圖表設定。"""
    conn = get_db_connection()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM DashboardCharts WHERE id = ?", (chart_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "圖表已刪除"})
    
    if request.method == 'PUT':
        data = request.json
        cursor = conn.cursor()
        cursor.execute("DELETE FROM DashboardSeries WHERE chart_id = ?", (chart_id,))
        cursor.execute(
            "UPDATE DashboardCharts SET chart_title=?, source_table_name=?, time_column=?, time_grouping=?, display_order=? WHERE id=?",
            (data['chart_title'], data['source_table_name'], data['time_column'], data['time_grouping'], data.get('display_order', 0), chart_id)
        )
        for series in data['series']:
            cursor.execute(
                 # *** 修改點：新增 aggregation_method ***
                "INSERT INTO DashboardSeries (chart_id, source_column_name, series_label, chart_type, y_axis_id, aggregation_method) VALUES (?, ?, ?, ?, ?, ?)",
                (chart_id, series['source_column_name'], series['series_label'], series['chart_type'], series['y_axis_id'], series['aggregation_method'])
            )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Chart updated"})

# =========================================================
#  ↓↓↓ EnPI 管理模組 API (基線整合版) ↓↓↓
# =========================================================

@app.route('/enpi')
def enpi_management():
    return render_template('enpi.html')

@app.route('/api/enpi/definitions', methods=['GET', 'POST'])
def handle_enpi_definitions():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            data = request.json
            conn.execute("""
                INSERT INTO EnPI_Definitions (
                    name, description, unit, higher_is_better,
                    numerator_source_type, numerator_manual_name, numerator_baseline_id, numerator_source_table, numerator_source_column, numerator_time_column, numerator_aggregation,
                    denominator_source_type, denominator_manual_name, denominator_baseline_id, denominator_source_table, denominator_source_column, denominator_time_column, denominator_aggregation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['name'], data.get('description'), data['unit'], data.get('higher_is_better', 0),
                data['numerator_source_type'], data.get('numerator_manual_name'), data.get('numerator_baseline_id'), data.get('numerator_source_table'), data.get('numerator_source_column'), data.get('numerator_time_column'), data.get('numerator_aggregation'),
                data['denominator_source_type'], data.get('denominator_manual_name'), data.get('denominator_baseline_id'), data.get('denominator_source_table'), data.get('denominator_source_column'), data.get('denominator_time_column'), data.get('denominator_aggregation')
            ))
            conn.commit()
            return jsonify({"success": True, "message": "EnPI 已建立"}), 201
        
        definitions = conn.execute("SELECT * FROM EnPI_Definitions ORDER BY name").fetchall()
        return jsonify([dict(row) for row in definitions])
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()
def _calculate_enpi_component(conn, definition, component_prefix, year):
    """輔助函式，用於計算分子或分母的值"""
    source_type = definition.get(f'{component_prefix}_source_type')
    
    if source_type == 'manual':
        manual_name = definition.get(f'{component_prefix}_manual_name')
        if not manual_name: return {}
        data_rows = conn.execute(
            "SELECT month, value FROM EnPI_Manual_Data WHERE enpi_id = ? AND year = ? AND variable_name = ?",
            (definition['id'], year, manual_name)
        ).fetchall()
        return {row['month']: row['value'] for row in data_rows}
    
    elif source_type == 'auto':
        agg = definition.get(f'{component_prefix}_aggregation')
        table = definition.get(f'{component_prefix}_source_table')
        column = definition.get(f'{component_prefix}_source_column')
        time_col = definition.get(f'{component_prefix}_time_column')
        
        if not all([agg, table, column, time_col]): 
            return {}
        
        query = f"""
            SELECT CAST(strftime('%m', "{time_col}") AS INTEGER) as month, {agg}("{column}") as value 
            FROM "{table}" WHERE strftime('%Y', "{time_col}") = '{year}' GROUP BY month
        """
        data_rows = conn.execute(query).fetchall()
        return {row['month']: row['value'] for row in data_rows}
    
    elif source_type == 'baseline':
        baseline_id = definition.get(f'{component_prefix}_baseline_id')
        source_col = definition.get(f'{component_prefix}_source_column')
        if not baseline_id or not source_col: 
            return {}
        
        data_map = {}
        monitored_data = conn.execute("SELECT month, actual_consumption, factors_json FROM MonitoredData WHERE baseline_id = ? AND year = ?", (baseline_id, year)).fetchall()
        for row in monitored_data:
            month = row['month']
            if source_col == 'actual_consumption':
                if row['actual_consumption'] is not None: 
                    data_map[month] = row['actual_consumption']
            else:
                factors = json.loads(row['factors_json']) if row['factors_json'] else {}
                if source_col in factors: 
                    data_map[month] = factors[source_col]
        return data_map
    
    return {}
# 在 app.py 中，找到並用這個【終極修正版】替換 handle_enpi_data 函式

@app.route('/api/enpi/data/<int:enpi_id>/<int:year>', methods=['GET', 'POST'])
def handle_enpi_data(enpi_id, year):
    conn = get_db_connection()
    try:
        enpi_def_row = conn.execute("SELECT * FROM EnPI_Definitions WHERE id = ?", (enpi_id,)).fetchone()
        if not enpi_def_row:
            return jsonify({"error": "EnPI not found"}), 404
        
        enpi_def = dict(enpi_def_row)

        if request.method == 'POST':
            data = request.json
            month = data.get('month')
            
            def upsert_manual_data(variable_name, value):
                if value is not None and value != '':
                    if variable_name:
                        conn.execute("""
                            INSERT INTO EnPI_Manual_Data (enpi_id, year, month, variable_name, value) 
                            VALUES (?, ?, ?, ?, ?) ON CONFLICT(enpi_id, year, month, variable_name) 
                            DO UPDATE SET value = excluded.value
                        """, (enpi_id, year, month, variable_name, float(value)))

            target_value = data.get('target_value')
            if target_value is not None and target_value != '':
                conn.execute("""
                    INSERT INTO EnPI_Targets (enpi_id, year, month, target_value) 
                    VALUES (?, ?, ?, ?) ON CONFLICT(enpi_id, year, month) 
                    DO UPDATE SET target_value = excluded.target_value
                """, (enpi_id, year, month, float(target_value)))
            
            if enpi_def.get('numerator_source_type') == 'manual':
                upsert_manual_data(enpi_def.get('numerator_manual_name'), data.get('numerator_value'))
            if enpi_def.get('denominator_source_type') == 'manual':
                upsert_manual_data(enpi_def.get('denominator_manual_name'), data.get('denominator_value'))

            conn.commit()
            return jsonify({"success": True, "message": f"{year}年{month}月數據已儲存"})

        numerators_map = _calculate_enpi_component(conn, enpi_def, 'numerator', year)
        denominators_map = _calculate_enpi_component(conn, enpi_def, 'denominator', year)
        
        targets_data = conn.execute("SELECT month, target_value FROM EnPI_Targets WHERE enpi_id = ? AND year = ?", (enpi_id, year)).fetchall()
        targets_map = {t['month']: t['target_value'] for t in targets_data}

        report = []
        for month in range(1, 13):
            num_raw = numerators_map.get(month)
            den_raw = denominators_map.get(month)
            
            actual_enpi = None
            
            try:
                num_val = float(num_raw) if num_raw is not None else None
                den_val = float(den_raw) if den_raw is not None else None
                
                if isinstance(num_val, (int, float)) and isinstance(den_val, (int, float)) and den_val != 0:
                    actual_enpi = num_val / den_val
            except (ValueError, TypeError):
                actual_enpi = None

            report.append({
                "month": month, "month_name": f"{month}月", 
                "target_value": targets_map.get(month), 
                "numerator_value": num_raw,
                "denominator_value": den_raw,
                "actual_enpi": actual_enpi
            })

        return jsonify({"definition": enpi_def, "report": report})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()
# =========================================================
#  ↓↓↓ 新增：異常事件與行動方案管理 API ↓↓↓
# =========================================================

@app.route('/events')
def event_management():
    """渲染事件管理頁面"""
    return render_template('events.html')

# --- API for Alarm Events ---

@app.route('/api/events', methods=['GET', 'POST'])
def handle_events():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            data = request.json
            print(f"Received POST data: {data}")
            if not data.get('event_title'):
                return jsonify({"error": "事件標題為必填欄位"}), 400
            due_date = validate_date(data.get('due_date'))
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO Alarm_Events (event_title, severity, assigned_to, due_date, event_time, status, event_type, impact_scope, root_cause) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    data['event_title'],
                    data.get('severity', 'medium'),
                    data.get('assigned_to'),
                    due_date,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'assigned',
                    data.get('event_type'),
                    data.get('impact_scope'),
                    data.get('root_cause')
                )
            )
            event_id = cursor.lastrowid
            conn.commit()
            
            if data.get('initial_description'):
                cursor.execute(
                    "INSERT INTO Action_Plans (event_id, action_type, content, author) VALUES (?, ?, ?, ?)",
                    (event_id, 'comment', data['initial_description'], 'system')
                )
                conn.commit()

            return jsonify({"success": True, "message": "事件已建立", "id": event_id}), 201

        status_filter = request.args.get('status', 'open')
        query = "SELECT * FROM Alarm_Events"
        params = []
        if status_filter != 'all':
            query += " WHERE status = ?"
            params.append(status_filter)
        query += " ORDER BY event_time DESC"
        
        events = conn.execute(query, params).fetchall()
        return jsonify([dict(row) for row in events])
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print(f"IntegrityError: {str(e)}")
        return jsonify({"error": f"資料庫錯誤：{str(e)}"}), 400
    except Exception as e:
        conn.rollback()
        print(f"Error in handle_events: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()

@app.route('/api/events/<int:event_id>', methods=['GET', 'PUT'])
def handle_single_event(event_id):
    conn = get_db_connection()
    try:
        if request.method == 'PUT':
            data = request.json
            # 只更新允許被修改的欄位
            conn.execute(
                "UPDATE Alarm_Events SET status = ?, severity = ?, assigned_to = ?, due_date = ? WHERE id = ?",
                (data.get('status'), data.get('severity'), data.get('assigned_to'), data.get('due_date'), event_id)
            )
            conn.commit()
            return jsonify({"success": True, "message": "事件已更新"})

        # GET
        event = conn.execute("SELECT * FROM Alarm_Events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            return jsonify({"error": "事件不存在"}), 404
        
        actions = conn.execute("SELECT * FROM Action_Plans WHERE event_id = ? ORDER BY created_at ASC", (event_id,)).fetchall()
        
        response = {
            "event": dict(event),
            "actions": [dict(row) for row in actions]
        }
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()


@app.route('/api/events/<int:event_id>/actions', methods=['POST'])
def add_action_plan(event_id):
    conn = get_db_connection()
    try:
        data = request.json
        if not data.get('content') or not data.get('action_type'):
            return jsonify({"error": "缺少必要參數"}), 400

        conn.execute(
            "INSERT INTO Action_Plans (event_id, action_type, content, author) VALUES (?, ?, ?, ?)",
            (event_id, data['action_type'], data['content'], data.get('author', 'user'))
        )
        conn.commit()
        return jsonify({"success": True, "message": "行動方案已新增"}), 201
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
    finally:
        if conn: conn.close()

# =========================================================        

if __name__ == '__main__':
    print("Flask 後端啟動於 http://127.0.0.1:5001")
    app.run(debug=True, port=5001)