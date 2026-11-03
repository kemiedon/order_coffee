(() => {
  const animatedItems = document.querySelectorAll(".wow");

  if (!animatedItems.length || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return;
  }

  if (typeof window.WOW === "function") {
    document.documentElement.classList.add("wow-ready");
    new window.WOW({
      animateClass: "animate__animated",
      offset: 80,
      live: false,
    }).init();
    return;
  }

  console.warn("WOW.js is unavailable; using IntersectionObserver for scroll animations.");

  if (!("IntersectionObserver" in window)) {
    animatedItems.forEach((item) => item.classList.add("animate__animated"));
    return;
  }

  const observer = new IntersectionObserver((entries, currentObserver) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("animate__animated");
        currentObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  animatedItems.forEach((item) => observer.observe(item));
})();
