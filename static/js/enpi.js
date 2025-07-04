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
    document.getElementById('add-enpi-btn').addEventListener('click', () => showEnpiEditor());
    
    const yearSelect = document.getElementById('select-year');
    const currentYear = new Date().getFullYear();
    for (let i = -2; i <= 2; i++) {
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

    const numHeader = definition.numerator_source_type === 'manual' ? definition.numerator_manual_name : `分子(能耗)`;
    const denHeader = definition.denominator_source_type === 'manual' ? definition.denominator_manual_name : `分母(變數)`;

    tableHead.innerHTML = `<tr><th>月份</th><th>目標值 (${definition.unit})</th><th>${numHeader}</th><th>${denHeader}</th><th>實際 EnPI (${definition.unit})</th><th>達成率 (%)</th></tr>`;
    tableBody.innerHTML = '';
    report.forEach(row => {
        const tr = document.createElement('tr');
        tr.dataset.month = row.month;
        const target = row.target_value ?? '';
        const numVal = row.numerator_value ?? '';
        const denVal = row.denominator_value ?? '';
        const actual = row.actual_enpi !== null ? parseFloat(row.actual_enpi).toFixed(2) : 'N/A';
        let achievementRate = 'N/A', rateClass = '';
        if (actual !== 'N/A' && target !== '' && parseFloat(target) > 0) {
            const achievement = definition.higher_is_better ? (parseFloat(actual) / target) : (target / parseFloat(actual));
            if (isFinite(achievement)) {
                achievementRate = (achievement * 100).toFixed(1);
                rateClass = achievement >= 1 ? 'highlight-green' : 'highlight-red';
            }
        }
        const numInput = `<input type="number" step="any" class="numerator-input" value="${numVal}" ${definition.numerator_source_type !== 'manual' ? 'readonly' : ''}>`;
        const denInput = `<input type="number" step="any" class="denominator-input" value="${denVal}" ${definition.denominator_source_type !== 'manual' ? 'readonly' : ''}>`;
        tr.innerHTML = `
            <td>${row.month_name}</td>
            <td><input type="number" step="any" class="target-input" value="${target}"></td>
            <td>${numInput}</td>
            <td>${denInput}</td>
            <td>${actual}</td>
            <td class="${rateClass}">${achievementRate === 'N/A' ? 'N/A' : achievementRate + '%'}</td>
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
                { label: `目標值`, data: report.map(r => r.target_value), borderColor: '#f5a623', backgroundColor: 'transparent', type: 'line', borderDash: [5, 5], yAxisID: 'y' },
                { label: `實際 EnPI`, data: report.map(r => r.actual_enpi), backgroundColor: '#4a90e2', yAxisID: 'y' }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { title: { display: true, text: `${definition.name} 績效追蹤圖`, font: { size: 16 } }, legend: { position: 'top' } },
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
        const payload = { 
            month: parseInt(month),
            target_value: row.querySelector('.target-input').value,
            numerator_value: row.querySelector('.numerator-input').value,
            denominator_value: row.querySelector('.denominator-input').value
        };
        if (payload.target_value !== '' || payload.numerator_value !== '' || payload.denominator_value !== '') {
            requests.push(apiFetch(`/api/enpi/data/${enpiId}/${year}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)}));
        }
    }
    if (requests.length > 0) { await Promise.all(requests); alert('數據已儲存！'); loadEnpiReport(); } 
    else { alert('沒有需要儲存的數據。'); }
}

// --- 定義新 EnPI 的彈出視窗邏輯 ---
async function showEnpiEditor() {
    const editor = document.getElementById('enpi-editor');
    const form = document.getElementById('enpi-def-form');
    
    const tables = await apiFetch('/api/config/tables');
    const baselines = await apiFetch('/api/regression_baselines');

    form.innerHTML = `
        <div class="form-section full-span">
            <h4>基本資訊</h4>
            <div class="form-group"><label>EnPI 名稱:</label><input type="text" name="name" required placeholder="例如：噸產品耗電量"></div>
            <div class="form-group"><label>EnPI 單位:</label><input type="text" name="unit" required placeholder="例如：kWh/噸"></div>
            <div class="form-group"><label>說明:</label><input type="text" name="description" placeholder="選填"></div>
        </div>
        
        <!-- 分子設定 -->
        <div class="form-section full-span">
            <h4>分子設定</h4>
            <div class="form-group"><label>來源類型:</label><select name="numerator_source_type"><option value="auto">從即時資料表計算</option><option value="manual">人工輸入</option><option value="baseline">從迴歸基線引用</option></select></div>
            <div class="numerator-manual-fields" style="display:none;"><div class="form-group"><label>變數名稱:</label><input type="text" name="numerator_manual_name"></div></div>
            <div class="numerator-auto-fields"><div class="form-group"><label>來源資料表:</label><select name="numerator_source_table"></select></div></div>
            <div class="numerator-auto-fields"><div class="form-group"><label>來源欄位 (數值):</label><select name="numerator_source_column"></select></div></div>
            <div class="numerator-auto-fields"><div class="form-group"><label>來源欄位 (時間):</label><select name="numerator_time_column"></select></div></div>
            <div class="numerator-auto-fields"><div class="form-group"><label>聚合方式:</label><select name="numerator_aggregation"><option value="SUM">總和</option><option value="AVG">平均</option></select></div></div>
            <div class="numerator-baseline-fields" style="display:none;"><div class="form-group"><label>選擇基線:</label><select name="numerator_baseline_id"></select></div><div class="form-group"><label>選擇欄位:</label><select name="numerator_source_column"></select></div></div>
        </div>
        
        <!-- 分母設定 -->
        <div class="form-section full-span">
            <h4>分母設定</h4>
            <div class="form-group"><label>來源類型:</label><select name="denominator_source_type"><option value="auto">從即時資料表計算</option><option value="manual">人工輸入</option><option value="baseline">從迴歸基線引用</option></select></div>
            <div class="denominator-manual-fields" style="display:none;"><div class="form-group"><label>變數名稱:</label><input type="text" name="denominator_manual_name"></div></div>
            <div class="denominator-auto-fields"><div class="form-group"><label>來源資料表:</label><select name="denominator_source_table"></select></div></div>
            <div class="denominator-auto-fields"><div class="form-group"><label>來源欄位 (數值):</label><select name="denominator_source_column"></select></div></div>
            <div class="denominator-auto-fields"><div class="form-group"><label>來源欄位 (時間):</label><select name="denominator_time_column"></select></div></div>
            <div class="denominator-auto-fields"><div class="form-group"><label>聚合方式:</label><select name="denominator_aggregation"><option value="SUM">總和</option><option value="AVG">平均</option></select></div></div>
            <div class="denominator-baseline-fields" style="display:none;"><div class="form-group"><label>選擇基線:</label><select name="denominator_baseline_id"></select></div><div class="form-group"><label>選擇欄位:</label><select name="denominator_source_column"></select></div></div>
        </div>

        <div class="form-group full-span"><label class="checkbox-label"><input type="checkbox" name="higher_is_better"> 指標數值越高越好 (預設為越低越好)</label></div>
        <div class="form-actions full-span"><button type="submit" class="primary">儲存定義</button><button type="button" id="cancel-enpi-editor" class="secondary">取消</button></div>
    `;
    
    // 為分子和分母兩個部分，分別設定所有事件監聽器
    ['numerator', 'denominator'].forEach(prefix => {
        const typeSelect = form.querySelector(`select[name="${prefix}_source_type"]`);
        const manualSection = form.querySelector(`.${prefix}-manual-fields`);
        const autoSection = form.querySelector(`.${prefix}-auto-fields`);
        const baselineSection = form.querySelector(`.${prefix}-baseline-fields`);
        
        const tableSelect = autoSection.querySelector(`select[name="${prefix}_source_table"]`);
        const baselineSelect = baselineSection.querySelector(`select[name="${prefix}_baseline_id"]`);

        // 填充下拉選單的初始數據
        if (tables) tables.forEach(t => tableSelect.add(new Option(t, t)));
        if (baselines) baselines.forEach(b => baselineSelect.add(new Option(`${b.year} - ${b.name}`, b.id)));

        // 1. 綁定來源類型切換事件，控制三個區塊的顯示/隱藏
        typeSelect.addEventListener('change', () => {
            const type = typeSelect.value;
            manualSection.style.display = type === 'manual' ? 'grid' : 'none';
            autoSection.style.display = type === 'auto' ? 'grid' : 'none';
            baselineSection.style.display = type === 'baseline' ? 'grid' : 'none';
        });
        typeSelect.dispatchEvent(new Event('change'));

        // 2. 綁定 'auto' 區塊的資料表切換事件
        tableSelect.addEventListener('change', async () => {
            const selectedTable = tableSelect.value;
            const colSelect = autoSection.querySelector(`select[name="${prefix}_source_column"]`);
            const timeColSelect = autoSection.querySelector(`select[name="${prefix}_time_column"]`);
            colSelect.innerHTML = ''; 
            timeColSelect.innerHTML = '';
            if (selectedTable) {
                const columns = await apiFetch(`/api/config/columns?table=${selectedTable}`);
                if(columns) columns.forEach(c => { colSelect.add(new Option(c, c)); timeColSelect.add(new Option(c, c)); });
            }
        });
        tableSelect.dispatchEvent(new Event('change'));

        // 3. 綁定 'baseline' 區塊的基線切換事件
        baselineSelect.addEventListener('change', async () => {
            const baselineId = baselineSelect.value;
            const colSelect = baselineSection.querySelector(`select[name="${prefix}_source_column"]`);
            colSelect.innerHTML = '';
            if (baselineId) {
                const details = await apiFetch(`/api/regression_baselines/${baselineId}`);
                if (details) {
                    colSelect.add(new Option('實際能耗', 'actual_consumption'));
                    details.factors.forEach(f => colSelect.add(new Option(f.factor_name, f.factor_name)));
                }
            }
        });
        baselineSelect.dispatchEvent(new Event('change'));
    });
    
    form.addEventListener('submit', handleEnpiDefSubmit);
    document.getElementById('cancel-enpi-editor').addEventListener('click', () => editor.style.display = 'none');
    
    editor.style.display = 'block';
}

async function handleEnpiDefSubmit(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const payload = {};
    
    // 收集所有欄位的值
    for (const [key, value] of formData.entries()) {
        payload[key] = value;
    }
    payload.higher_is_better = payload.higher_is_better ? 1 : 0;

    const result = await apiFetch('/api/enpi/definitions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (result && result.success) {
        alert(result.message);
        document.getElementById('enpi-editor').style.display = 'none';
        loadEnpiDefinitions();
    }
}