// Recon ROI & Time Savings Calculator
(function() {
  const STORAGE_KEY = "recon_calc_inputs_v1";

  const DEFAULTS = {
    reconsPerMonth: 35,
    rowsPerRecon: 400,
    minsPerRow: 1.2,
    hourlyCost: 350
  };

  function loadInputs() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return { ...DEFAULTS, ...JSON.parse(saved) };
    } catch (e) {}
    return DEFAULTS;
  }

  function saveInputs(data) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {}
  }

  function calculate(inputs) {
    const totalRowsMonth = inputs.reconsPerMonth * inputs.rowsPerRecon;
    const manualHoursMonth = (totalRowsMonth * inputs.minsPerRow) / 60;
    const manualCostMonth = manualHoursMonth * inputs.hourlyCost;
    const manualCostYear = manualCostMonth * 12;

    const assistRate = 0.70; // 70% assist rate benchmark
    const hoursSavedMonth = manualHoursMonth * assistRate;
    const moneySavedMonth = hoursSavedMonth * inputs.hourlyCost;
    const moneySavedYear = moneySavedMonth * 12;

    // Firm subscription plan: ₹6,000 / month
    const reconMonthlyCost = totalRowsMonth > 10000 ? 12000 : 6000;
    const netSavingsMonth = Math.max(0, moneySavedMonth - reconMonthlyCost);
    const paybackWeeks = moneySavedMonth > 0 ? (reconMonthlyCost / (moneySavedMonth / 4.33)) : 0;

    return {
      totalRowsMonth,
      manualHoursMonth: Math.round(manualHoursMonth),
      manualCostMonth: Math.round(manualCostMonth),
      manualCostYear: Math.round(manualCostYear),
      hoursSavedMonth: Math.round(hoursSavedMonth),
      moneySavedMonth: Math.round(moneySavedMonth),
      moneySavedYear: Math.round(moneySavedYear),
      paybackWeeks: paybackWeeks.toFixed(1),
      reconMonthlyCost
    };
  }

  function formatRupees(num) {
    return "₹" + Number(num).toLocaleString("en-IN");
  }

  function initCalculator() {
    const reconsInput = document.getElementById("calc-recons");
    const rowsInput = document.getElementById("calc-rows");
    const minsInput = document.getElementById("calc-mins");
    const costInput = document.getElementById("calc-cost");

    if (!reconsInput || !rowsInput || !minsInput || !costInput) return;

    const state = loadInputs();
    reconsInput.value = state.reconsPerMonth;
    rowsInput.value = state.rowsPerRecon;
    minsInput.value = state.minsPerRow;
    costInput.value = state.hourlyCost;

    function update() {
      const inputs = {
        reconsPerMonth: parseFloat(reconsInput.value) || 0,
        rowsPerRecon: parseFloat(rowsInput.value) || 0,
        minsPerRow: parseFloat(minsInput.value) || 0,
        hourlyCost: parseFloat(costInput.value) || 0
      };
      saveInputs(inputs);
      const res = calculate(inputs);

      const hoursElem = document.getElementById("out-hours-saved");
      const annualElem = document.getElementById("out-annual-saved");
      const paybackElem = document.getElementById("out-payback-weeks");
      const manualHoursElem = document.getElementById("out-manual-hours");

      if (hoursElem) hoursElem.textContent = `${res.hoursSavedMonth} hrs/mo`;
      if (annualElem) annualElem.textContent = formatRupees(res.moneySavedYear);
      if (paybackElem) paybackElem.textContent = `${res.paybackWeeks} weeks`;
      if (manualHoursElem) manualHoursElem.textContent = `${res.manualHoursMonth} hrs/mo (${formatRupees(res.manualCostMonth)})`;

      const noteElem = document.getElementById("calc-formula-display");
      if (noteElem) {
        noteElem.textContent = `Formula: (${inputs.reconsPerMonth} recons × ${inputs.rowsPerRecon} rows × ${inputs.minsPerRow}m ÷ 60) × 70% assist × ₹${inputs.hourlyCost}/hr`;
      }
    }

    [reconsInput, rowsInput, minsInput, costInput].forEach(inp => {
      inp.addEventListener("input", update);
    });

    update();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initCalculator);
  } else {
    initCalculator();
  }
})();
