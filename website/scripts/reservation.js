(() => {
  const localDate = new Date();
  const today = [
    localDate.getFullYear(),
    String(localDate.getMonth() + 1).padStart(2, "0"),
    String(localDate.getDate()).padStart(2, "0"),
  ].join("-");

  document.querySelectorAll(".reservation-form").forEach((form) => {
    const dateInput = form.elements.namedItem("date");
    const status = form.querySelector(".reservation-status");

    dateInput.min = today;

    const validateDate = () => {
      dateInput.setCustomValidity("");
      if (!dateInput.value) {
        return;
      }

      const selectedDate = new Date(`${dateInput.value}T00:00:00`);
      if (selectedDate.getDay() === 0) {
        dateInput.setCustomValidity("每週日公休，請選擇週一至週六。");
      }
    };

    dateInput.addEventListener("change", validateDate);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      validateDate();
      status.hidden = true;
      status.classList.remove("reservation-status--error");

      if (!form.reportValidity()) {
        return;
      }

      status.textContent = "資料格式檢查完成；目前尚未串接寄送服務，預約尚未送出或成立。";
      status.hidden = false;
    });
  });
})();
