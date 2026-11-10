// Shadow Month Intake Form Handler
(function() {
  function initShadowForm() {
    const form = document.getElementById("shadow-month-form");
    if (!form) return;

    const feedback = document.getElementById("form-feedback");
    const submitBtn = form.querySelector('button[type="submit"]');

    form.addEventListener("submit", async function(e) {
      e.preventDefault();
      const name = (document.getElementById("lead-name")?.value || "").trim();
      const firm = (document.getElementById("lead-firm")?.value || "").trim();
      const email = (document.getElementById("lead-email")?.value || "").trim();

      if (!name || !firm || !email || !email.includes("@")) {
        showFeedback("Please provide your name, CA firm name, and a valid work email.", "error");
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Submitting...";
      }

      try {
        const res = await fetch("/api/shadow-month", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, firm, email })
        });

        const data = await res.json();
        if (res.ok) {
          showFeedback("Thank you. We have received your shadow-month request. We will contact you within one business day.", "success");
          form.reset();
        } else {
          showFeedback(data.detail || "Error submitting form. Please try again.", "error");
        }
      } catch (err) {
        showFeedback("Network error. Please try again or email us directly.", "error");
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Start Free Shadow Month";
        }
      }
    });

    function showFeedback(msg, type) {
      if (!feedback) return;
      feedback.style.display = "block";
      feedback.className = type === "success" ? "alert-success" : "alert-error";
      feedback.textContent = msg;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initShadowForm);
  } else {
    initShadowForm();
  }
})();
