document.addEventListener('DOMContentLoaded', () => {
    setupEnpiPage();
    loadEnpiDefinitions();
});

let enpiChart = null;

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

// --- 頁面初始化與事件綁定 ---
function setupEnpiPage() {
    document.getElementById('select-enpi').addEventListener('change', loadEnpiReport);
    document.getElementById('select-year').addEventListener('change', loadEnpiReport);
    document.getElementById('save-enpi-data-btn').addEventListener('click', saveEnpiData);
    document.getElementById('add-enpi-btn').addEventListener('click', showEnpiEditor);
    
    // 初始化年份選擇器
    const yearSelect = document.getElementById('select-year');
    const currentYear = new Date().getFullYear();
    for (let i = -2; i <= 2; i++) { // 顯示前後兩年
        const year = currentYear + i;
        yearSelect.add(new Option(year, year));
    }
    yearSelect.value = currentYear;
}

// --- 主要功能函式 ---
async function loadEnpiDefinitions() {
    const enpis = await apiFetch('/api/enpi/definitions');
    const select = document.getElementById('select-enpi');
    const currentVal = select.value;
    select.innerHTML = '<option value="">-- 請選擇 --</option>';
    if (enpis) {
        enpis.forEach(e => select.add(new Option(e.name, e.id)));
    }
    select.value = currentVal;
    if (currentVal) {
        loadEnpiReport();
    }
}

async function loadEnpiReport() {
    const enpiId = document.getElementById('select-enpi').value;
    const year = document.getElementById('select-year').value;
    const dataSection = document.getElementById('enpi-data-section');

    if (!enpiId || !year) {
        dataSection.style.display = 'none';
        return;
    }

    const data = await apiFetch(`/api/enpi/data/${enpiId}/${year}`);
    if (!data) return;
    
    renderEnpiTable(data);
    renderEnpiChart(data);
    dataSection.style.display = 'block';
}

function renderEnpiTable(data) {
    const { definition, report } = data;
    document.getElementById('enpi-title').textContent = `${definition.name} (${definition.unit})`;
    const tableHead = document.getElementById('enpi-table').querySelector('thead');
    const tableBody = document.getElementById('enpi-table').querySelector('tbody');

    tableHead.innerHTML = `
        <tr>
            <th>月份</th>
            <th>目標值 (${definition.unit})</th>
            <th>${definition.denominator_variable_name} (${definition.denominator_unit})</th>
            <th>分子(能耗) (${definition.numerator_aggregation})</th>
            <th>實際 EnPI (${definition.unit})</th>
            <th>達成率 (%)</th>
        </tr>
    `;

    tableBody.innerHTML = '';
    report.forEach(row => {
        const tr = document.createElement('tr');
        tr.dataset.month = row.month;

        const target = row.target_value ?? '';
        const variable = row.variable_value ?? '';
        const numerator = row.numerator_value !== null ? parseFloat(row.numerator_value).toFixed(2) : 'N/A';
        const actual = row.actual_enpi !== null ? parseFloat(row.actual_enpi).toFixed(2) : 'N/A';
        
        let achievementRate = 'N/A';
        if (actual !== 'N/A' && target !== '') {
            if (definition.higher_is_better) {
                achievementRate = ((parseFloat(actual) / target) * 100).toFixed(1);
            } else {
                // 越低越好，達成率 = (目標 / 實際) * 100
                achievementRate = ((target / parseFloat(actual)) * 100).toFixed(1);
            }
        }
        
        tr.innerHTML = `
            <td>${row.month_name}</td>
            <td><input type="number" step="any" class="target-input" value="${target}"></td>
            <td><input type="number" step="any" class="variable-input" value="${variable}"></td>
            <td>${numerator}</td>
            <td>${actual}</td>
            <td class="${parseFloat(achievementRate) >= 100 ? 'highlight-green' : 'highlight-red'}">${achievementRate}%</td>
        `;
        tableBody.appendChild(tr);
    });
}

function renderEnpiChart(data) {
    const { definition, report } = data;
    const ctx = document.getElementById('enpi-chart').getContext('2d');
    if (enpiChart) enpiChart.destroy();

    enpiChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: report.map(r => r.month_name),
            datasets: [
                {
                    label: `目標值 (${definition.unit})`,
                    data: report.map(r => r.target_value),
                    borderColor: '#f5a623',
                    backgroundColor: 'transparent',
                    type: 'line',
                    borderDash: [5, 5],
                    yAxisID: 'y'
                },
                {
                    label: `實際 EnPI (${definition.unit})`,
                    data: report.map(r => r.actual_enpi),
                    backgroundColor: '#4a90e2',
                    yAxisID: 'y'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: `${definition.name} 績效追蹤圖`, font: { size: 16 } },
                legend: { position: 'top' }
            },
            scales: { y: { beginAtZero: false, title: { display: true, text: definition.unit } } }
        }
    });
}

async function saveEnpiData() {
    const enpiId = document.getElementById('select-enpi').value;
    const year = document.getElementById('select-year').value;
    const tableBody = document.getElementById('enpi-table').querySelector('tbody');
    
    const requests = [];
    for (const row of tableBody.rows) {
        const month = row.dataset.month;
        const target_value = row.querySelector('.target-input').value;
        const variable_value = row.querySelector('.variable-input').value;

        // 只有當使用者輸入了值才發送請求
        if (target_value !== '' || variable_value !== '') {
            const payload = { month: parseInt(month), target_value, variable_value };
            requests.push(apiFetch(`/api/enpi/data/${enpiId}/${year}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }));
        }
    }

    if (requests.length > 0) {
        await Promise.all(requests);
        alert('數據已儲存！');
        loadEnpiReport();
    } else {
        alert('沒有需要儲存的數據。');
    }
}

// --- 定義新 EnPI 的彈出視窗邏輯 ---
async function showEnpiEditor() {
    const editor = document.getElementById('enpi-editor');
    const form = document.getElementById('enpi-def-form');
    
    // 動態獲取資料表和欄位資訊來填充下拉選單
    const tables = await apiFetch('/api/config/tables');
    
    // --- ↓↓↓ 修改點：增加 numerator_time_column 的 HTML ---
    form.innerHTML = `
        <div class="form-group"><label>EnPI 名稱:</label><input type="text" name="name" required placeholder="例如：噸產品耗電量"></div>
        <div class="form-group"><label>EnPI 單位:</label><input type="text" name="unit" required placeholder="例如：kWh/噸"></div>
        <div class="form-group"><label>說明:</label><input type="text" name="description" placeholder="選填"></div>
        <hr class="full-width">
        <h4 class="full-width">分子 (能源消耗)</h4>
        <div class="form-group"><label>來源資料表:</label><select name="numerator_source_table" required></select></div>
        <div class="form-group"><label>來源欄位 (數值):</label><select name="numerator_source_column" required></select></div>
        <div class="form-group"><label>來源欄位 (時間):</label><select name="numerator_time_column" required></select></div>
        <div class="form-group"><label>聚合方式:</label><select name="numerator_aggregation"><option value="SUM">總和 (Sum)</option><option value="AVG">平均 (Avg)</option></select></div>
        <hr class="full-width">
        <h4 class="full-width">分母 (產出或變數)</h4>
        <div class="form-group"><label>變數名稱:</label><input type="text" name="denominator_variable_name" required placeholder="例如：產量"></div>
        <div class="form-group"><label>變數單位:</label><input type="text" name="denominator_unit" required placeholder="例如：噸"></div>
        <div class="form-group full-width"><label><input type="checkbox" name="higher_is_better"> 指標數值越高越好 (預設為越低越好)</label></div>
        <div class="form-group full-width">
            <button type="submit" class="primary">儲存定義</button>
            <button type="button" id="cancel-enpi-editor" class="secondary">取消</button>
        </div>
    `;
    // --- ↑↑↑ 修改結束 ↑↑↑ ---
    
    const tableSelect = form.querySelector('select[name="numerator_source_table"]');
    if(tables) tables.forEach(t => tableSelect.add(new Option(t,t)));

    tableSelect.addEventListener('change', async (e) => {
        const selectedTable = e.target.value;
        const colSelect = form.querySelector('select[name="numerator_source_column"]');
        colSelect.innerHTML = '';
        if (selectedTable) {
            const columns = await apiFetch(`/api/config/columns?table=${selectedTable}`);
            if(columns) columns.forEach(c => colSelect.add(new Option(c,c)));
        }
    });

    form.addEventListener('submit', handleEnpiDefSubmit);
    document.getElementById('cancel-enpi-editor').addEventListener('click', () => editor.style.display = 'none');

    editor.style.display = 'block';
}

async function handleEnpiDefSubmit(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const payload = Object.fromEntries(formData.entries());
    payload.higher_is_better = payload.higher_is_better ? 1 : 0; // 轉換為 0 或 1

    const result = await apiFetch('/api/enpi/definitions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (result && result.success) {
        alert(result.message);
        document.getElementById('enpi-editor').style.display = 'none';
        loadEnpiDefinitions(); // 刷新 EnPI 列表
    }
}