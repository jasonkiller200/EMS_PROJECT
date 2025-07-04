// --- 全域變數 ---
const chartColors = ['#3498db', '#e74c3c', '#2ecc71', '#f1c40f', '#9b59b6', '#1abc9c'];
let dashboardRefreshInterval;
const chartInstances = {};
let dashboardBaselineChart = null;

// --- 初始化 ---
document.addEventListener('DOMContentLoaded', () => {
    // 1. 設定動態圖表區塊
    setupDashboardPage();
    loadDashboardCharts();
    startDashboardRefresh(); // 頁面載入時就開始自動刷新

    // 2. 設定能源基線圖表區塊
    setupBaselineChartSection();
    loadBaselinesForSelect();
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


// --- 動態圖表邏輯 ---
function setupDashboardPage() {
    document.getElementById('toggle-refresh-btn').addEventListener('click', toggleDashboardRefresh);
    document.getElementById('refresh-interval').addEventListener('change', restartDashboardRefresh);
}

function startDashboardRefresh() {
    if (dashboardRefreshInterval) clearInterval(dashboardRefreshInterval);
    const intervalInput = document.getElementById('refresh-interval');
    const intervalSeconds = parseInt(intervalInput.value, 10);
    
    if (intervalSeconds && intervalSeconds >= 10) {
        dashboardRefreshInterval = setInterval(loadDashboardCharts, intervalSeconds * 1000);
        document.getElementById('toggle-refresh-btn').textContent = "暫停刷新";
    }
}

function stopDashboardRefresh() {
    if (dashboardRefreshInterval) clearInterval(dashboardRefreshInterval);
    dashboardRefreshInterval = null;
    document.getElementById('toggle-refresh-btn').textContent = "開始刷新";
}

function toggleDashboardRefresh() {
    dashboardRefreshInterval ? stopDashboardRefresh() : startDashboardRefresh();
}

function restartDashboardRefresh() {
    stopDashboardRefresh();
    startDashboardRefresh();
}

async function loadDashboardCharts() {
    console.log("正在更新動態監控圖表...");
    const data = await apiFetch('/api/realtime_dashboard');
    const grid = document.getElementById('charts-grid');
    if (!data) {
        grid.innerHTML = '<p>無法載入圖表數據，請檢查後端服務。</p>';
        return;
    }

    grid.innerHTML = ''; // 清空舊內容

    if (data.length === 0) {
        grid.innerHTML = '<p>目前沒有設定任何圖表。請至「儀表板設定」頁面新增。</p>';
        return;
    }

    data.forEach((chartData, index) => {
        const card = document.createElement('div');
        card.className = 'chart-card';
        const canvasId = `dashboard-chart-${index}`;
        card.innerHTML = `<canvas id="${canvasId}"></canvas>`;
        grid.appendChild(card);

        if (chartInstances[canvasId]) {
            chartInstances[canvasId].destroy();
        }

        const ctx = document.getElementById(canvasId).getContext('2d');
        const datasets = chartData.datasets.map((ds, i) => ({
            ...ds, // 直接使用後端傳來的設定
            borderColor: chartColors[i % chartColors.length],
            backgroundColor: chartColors[i % chartColors.length] + '80', // '80' for transparency
            fill: ds.type === 'bar',
        }));
          // =========================================================
        //  ↓↓↓ 這裡是修改的核心：更智慧的 Y 軸設定 ↓↓↓
        // =========================================================

        const yAxesConfig = {};
const yAxesData = { y: [], y1: [] };

// 1. 分別收集左右 Y 軸的數據和標籤
datasets.forEach(ds => {
    const axisID = ds.yAxisID === 'y1' ? 'y1' : 'y';
    yAxesData[axisID].push(...ds.data);
    
    if (!yAxesConfig[axisID]) {
        yAxesConfig[axisID] = {
            labels: [],
            type: 'linear',
            display: true,
            position: axisID === 'y1' ? 'right' : 'left',
            grid: { drawOnChartArea: axisID === 'y1' ? false : true },
            // 移除 beginAtZero: true
        };
    }
    yAxesConfig[axisID].labels.push(ds.label);
});

// 2. 為每個使用到的 Y 軸，動態計算最大/最小值並設定標題
for (const axisID in yAxesConfig) {
    const validData = yAxesData[axisID].filter(d => d !== null && !isNaN(d));
    
    if (validData.length > 0) {
        const maxVal = Math.max(...validData);
        const minVal = Math.min(...validData);
        
        // 計算數據範圍
        const dataRange = maxVal - minVal;

        // 設定 Y 軸的最大/最小值，並增加 10% 的上下緩衝
        // 如果數據範圍是 0 (所有值都一樣)，則給一個小範圍
        if (dataRange > 0) {
            yAxesConfig[axisID].min = minVal - dataRange * 0.1;
            yAxesConfig[axisID].max = maxVal + dataRange * 0.1;
        } else {
            // 如果所有值都一樣，例如都是 50
            // 則將 Y 軸範圍設為 50 ± 5
            yAxesConfig[axisID].min = minVal - 5; 
            yAxesConfig[axisID].max = maxVal + 5;
        }

    } else {
        // 如果沒有數據，給一個預設範圍
        yAxesConfig[axisID].min = 0;
        yAxesConfig[axisID].max = 10;
    }

    // 將收集到的標籤組合為 Y 軸標題
    yAxesConfig[axisID].title = {
        display: true,
        text: yAxesConfig[axisID].labels.join(' / ')
    };
}
        // =========================================================
        //  ↑↑↑ 修改核心結束 ↑↑↑
        // =========================================================
        chartInstances[canvasId] = new Chart(ctx, {
            type: 'bar', // 預設類型，會被 dataset 中的 type 覆蓋
            data: { labels: chartData.labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                 // =========================================================
        //  ↓↓↓ 這裡是關鍵的修改點 ↓↓↓
        // =========================================================
                aspectRatio: 1.3, // 建議值：從 1.5 開始嘗試。數字越小，圖表越高。1 代表正方形。
        // =========================================================
                plugins: {
                    title: { display: true, text: chartData.tableName, font: { size: 16 } },
                    legend: { display: true, position: 'top' }
                },
                scales: {
                     x: { 
                title: { display: true, text: '時間' } 
            },
            // 將 yAxesConfig 的內容解構到 scales 中
            ...yAxesConfig
                }
            }
        });
    });
}


// --- 能源基線績效圖表邏輯 ---
function setupBaselineChartSection() {
    const selectElement = document.getElementById('select-baseline-for-dashboard');
    if (selectElement) {
        selectElement.addEventListener('change', (e) => {
            const baselineId = e.target.value;
            const container = document.getElementById('baseline-chart-container');
            if (baselineId) {
                container.style.display = 'block';
                loadAndDrawBaselineChart(baselineId);
            } else {
                container.style.display = 'none';
            }
        });
    }
}

async function loadBaselinesForSelect() {
    const baselines = await apiFetch('/api/regression_baselines');
    const select = document.getElementById('select-baseline-for-dashboard');
    if (!select) return;

    select.innerHTML = '<option value="">-- 請選擇要檢視的基線 --</option>';
    if (baselines) {
        baselines.forEach(b => select.add(new Option(`${b.year} - ${b.name}`, b.id)));
    }
}

async function loadAndDrawBaselineChart(baselineId) {
    const data = await apiFetch(`/api/regression_baselines/${baselineId}`);
    if (!data) return;
    
    const reportData = calculateReportData(data); // 計算圖表所需數據

    const ctx = document.getElementById('dashboard-baseline-chart').getContext('2d');
    if (dashboardBaselineChart) {
        dashboardBaselineChart.destroy();
    }
    
    dashboardBaselineChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: reportData.map(d => d.month),
            datasets: [
                {
                    label: '基線標準',
                    data: reportData.map(d => d.baseline),
                    borderColor: 'rgb(255, 99, 132)',
                    backgroundColor: 'rgba(255, 99, 132, 0.5)',
                    type: 'line', // 基線用線條表示
                    fill: false,
                    borderDash: [5, 5],
                    yAxisID: 'y',
                },
                {
                    label: '實際能耗',
                    data: reportData.map(d => d.actual),
                    borderColor: 'rgb(54, 162, 235)',
                    backgroundColor: 'rgba(54, 162, 235, 0.7)',
                    type: 'line', // 實際值用長條圖表示
                    yAxisID: 'y',
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: `能源基線績效 - ${data.baseline.name}`, font: { size: 16 } },
                legend: { position: 'top' }
            },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: '能耗' } }
            }
        }
    });
}

// 輔助函式：從 API 回應計算出報表數據
function calculateReportData(apiData) {
    const reportData = [];
    const formula = { intercept: apiData.baseline.formula_intercept, factors: apiData.factors };

    for (let month = 1; month <= 12; month++) {
        const monthData = apiData.monitored_data[month] || {};
        const factorsData = monthData.factors || {};
        const actualConsumption = monthData.actual_consumption;

        let baselineStandard = formula.intercept;
        let allFactorsPresent = true;
        
        formula.factors.forEach(f => {
            const factorValue = factorsData[f.factor_name];
            if (factorValue === undefined || factorValue === null || factorValue === '') {
                allFactorsPresent = false;
            } else {
                baselineStandard += parseFloat(factorValue) * f.coefficient;
            }
        });

        reportData.push({
            month: `${month}月`,
            baseline: allFactorsPresent ? baselineStandard.toFixed(2) : null,
            actual: (actualConsumption !== null && actualConsumption !== undefined) ? actualConsumption : null,
        });
    }
    return reportData;
}