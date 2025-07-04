// --- 初始化 ---
document.addEventListener('DOMContentLoaded', () => {
    // 綁定所有事件監聽器
    setupAdminPage();
    // 頁面載入時，就去讀取所有已儲存的圖表設定並顯示列表
    loadAllChartConfigs();
});


// --- 共用函式 ---
async function apiFetch(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `伺服器錯誤，狀態碼: ${response.status}` }));
            throw new Error(errorData.error || `HTTP 錯誤!`);
        }
        return response.json();
    } catch (error) {
        console.error('API 請求失敗:', url, error);
        alert(`操作失敗: ${error.message}`);
        return null;
    }
}


// --- 儀表板設定頁面 (Admin Page) 邏輯 ---

function setupAdminPage() {
    document.getElementById('add-new-chart-btn')?.addEventListener('click', showChartEditorForNew);
    document.getElementById('add-series-btn')?.addEventListener('click', () => addSeriesRow());
    document.getElementById('source-table')?.addEventListener('change', populateColumnSelectors);
    document.getElementById('chart-config-form')?.addEventListener('submit', saveChartConfig);
    document.getElementById('cancel-edit-btn')?.addEventListener('click', () => {
        const editor = document.getElementById('chart-editor');
        if (editor) editor.style.display = 'none';
    });
}

async function loadAllChartConfigs() {
    const charts = await apiFetch('/api/config/charts');
    const listContainer = document.getElementById('chart-config-list');
    if (!listContainer) return;

    listContainer.innerHTML = '';
    if (charts && charts.length > 0) {
        charts.forEach(chart => {
            const chartDiv = document.createElement('div');
            // 這裡可以加上 CSS class 來美化
            chartDiv.className = 'config-item'; // 使用 class 方便用 CSS 控制樣式
            chartDiv.innerHTML = `
                <span><strong>${chart.chart_title}</strong> (來源: ${chart.source_table_name})</span>
                <div>
                    <button onclick="editChartConfig(${chart.id})">編輯</button>
                    <button onclick="deleteChartConfig(${chart.id})" class="secondary">刪除</button>
                </div>
            `;
            listContainer.appendChild(chartDiv);
        });
    } else if (charts) {
        listContainer.innerHTML = '<p>尚未設定任何圖表。請點擊上方「新增圖表」按鈕開始。</p>';
    }
}

async function showChartEditorForNew() {
    const editor = document.getElementById('chart-editor');
    const form = document.getElementById('chart-config-form');
    if (!editor || !form) return;

    form.reset();
    document.getElementById('edit-chart-id').value = '';
    document.getElementById('editor-title').textContent = '新增圖表';
    document.getElementById('series-container').innerHTML = '';
    
    const tables = await apiFetch('/api/config/tables');
    const tableSelect = document.getElementById('source-table');
    tableSelect.innerHTML = '<option value="">-- 請選擇資料表 --</option>';
    if(tables) tables.forEach(t => tableSelect.add(new Option(t, t)));
    
    editor.style.display = 'block';
    addSeriesRow();
}

async function populateColumnSelectors() {
    const tableName = document.getElementById('source-table').value;
    const columns = tableName ? await apiFetch(`/api/config/columns?table=${tableName}`) : null;
    
    const timeSelect = document.getElementById('time-column');
    const currentTime = timeSelect.value;
    timeSelect.innerHTML = '';
    if (columns) {
        columns.forEach(c => timeSelect.add(new Option(c, c)));
        timeSelect.value = currentTime;
    }
    
    document.querySelectorAll('.series-column-select').forEach(select => {
        const currentVal = select.value;
        select.innerHTML = '<option value="">-- 選擇欄位 --</option>';
        if (columns) columns.forEach(c => select.add(new Option(c, c)));
        select.value = currentVal;
    });
}

function addSeriesRow(seriesData = {}) {
    const container = document.getElementById('series-container');
    const seriesRow = document.createElement('div');
    seriesRow.className = 'series-row form-group';
    seriesRow.innerHTML = `
        <select class="series-column-select" required title="分析欄位"></select>
        <input type="text" class="series-label" placeholder="序列標籤" required title="圖例標籤">
        <select class="series-agg-method" title="統計方式">
            <option value="avg">平均 (Avg)</option>
            <option value="sum">累加 (Sum)</option>
        </select>
        <select class="series-chart-type" title="圖表類型">
            <option value="bar">長條圖</option>
            <option value="line">折線圖</option>
        </select>
        <select class="series-y-axis" title="Y軸">
            <option value="y">左 Y 軸</option>
            <option value="y1">右 Y 軸</option>
        </select>
        <button type="button" onclick="this.parentElement.remove()" class="secondary">移除</button>
    `;
    container.appendChild(seriesRow);
    
    if(seriesData.source_column_name) {
        populateColumnSelectors().then(() => {
            seriesRow.querySelector('.series-column-select').value = seriesData.source_column_name;
        });
        seriesRow.querySelector('.series-label').value = seriesData.series_label;
        seriesRow.querySelector('.series-agg-method').value = seriesData.aggregation_method || 'avg';
        seriesRow.querySelector('.series-chart-type').value = seriesData.chart_type;
        seriesRow.querySelector('.series-y-axis').value = seriesData.y_axis_id;
    } else {
        populateColumnSelectors();
    }
}

async function saveChartConfig(e) {
    e.preventDefault();
    const chartId = document.getElementById('edit-chart-id').value;
    
    const series = Array.from(document.querySelectorAll('.series-row')).map(row => ({
        source_column_name: row.querySelector('.series-column-select').value,
        series_label: row.querySelector('.series-label').value,
        aggregation_method: row.querySelector('.series-agg-method').value,
        chart_type: row.querySelector('.series-chart-type').value,
        y_axis_id: row.querySelector('.series-y-axis').value,
    }));

    if (series.length === 0) {
        alert("請至少新增一個資料序列！");
        return;
    }

    const payload = {
        chart_title: document.getElementById('chart-title').value,
        source_table_name: document.getElementById('source-table').value,
        time_column: document.getElementById('time-column').value,
        time_grouping: document.getElementById('time-grouping').value,
        series: series
    };

    const url = chartId ? `/api/config/charts/${chartId}` : '/api/config/charts';
    const method = chartId ? 'PUT' : 'POST';

    const result = await apiFetch(url, {
        method: method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });

    if(result && result.success) {
        alert(result.message);
        document.getElementById('chart-editor').style.display = 'none';
        loadAllChartConfigs(); // 重新整理列表
    }
}

async function editChartConfig(chartId) {
    const allConfigs = await apiFetch('/api/config/charts');
    const chartData = allConfigs.find(c => c.id === chartId);
    if (!chartData) { alert("找不到圖表設定"); return; }
    
    await showChartEditorForNew(); 
    
    document.getElementById('editor-title').textContent = '編輯圖表';
    document.getElementById('edit-chart-id').value = chartData.id;
    document.getElementById('chart-title').value = chartData.chart_title;
    
    const tableSelect = document.getElementById('source-table');
    tableSelect.value = chartData.source_table_name;
    await populateColumnSelectors();
    
    document.getElementById('time-column').value = chartData.time_column;
    document.getElementById('time-grouping').value = chartData.time_grouping;
    
    document.getElementById('series-container').innerHTML = '';
    chartData.series.forEach(s => addSeriesRow(s));
}

async function deleteChartConfig(chartId) {
    if (confirm("確定要刪除這個圖表設定嗎？此操作無法復原。")) {
        const result = await apiFetch(`/api/config/charts/${chartId}`, { method: 'DELETE' });
        if (result && result.success) {
            alert(result.message);
            loadAllChartConfigs(); // 重新整理列表
        }
    }
}