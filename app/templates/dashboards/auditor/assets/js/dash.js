// Toggle Sidebar
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    const menuIcon = document.querySelector(".menu-icon i"); // Get the current icon

    // Toggle the icon when the sidebar opens or closes
    if (menuIcon.classList.contains("bx-menu")) {
        menuIcon.classList.replace("bx-menu", "bx-x"); // Switch to close icon
    } else {
        menuIcon.classList.replace("bx-x", "bx-menu"); // Switch back to menu icon
    }
}

// Function to close the sidebar when clicking outside
function closeSidebarIfClickedOutside(event) {
    const sidebar = document.getElementById("sidebar");
    const menuIcon = document.querySelector(".menu-icon i");
    
    // Check if the click is outside the sidebar and not on the menu icon
    if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
        sidebar.classList.remove("open");
        menuIcon.classList.replace("bx-x", "bx-menu"); // Revert the icon back to the menu
    }
}

// Add the event listener to close sidebar if clicking outside
document.addEventListener("click", closeSidebarIfClickedOutside);


function toggleSubmenu(event) {
  event.preventDefault(); // Prevents page reload

  let parent = event.target.closest(".submenu"); // Find the clicked <li>
  let submenu = parent.querySelector(".submenu-items"); // Find submenu in this <li>

  // Close all other submenus before opening the clicked one
  document.querySelectorAll(".submenu-items").forEach((item) => {
    if (item !== submenu) {
      item.classList.remove("open"); // Use class to control the display
      item.style.display = "none"; // Remove inline style if necessary
      item.parentElement.classList.remove("open");
    }
  });

  // Toggle the clicked submenu
  if (submenu.classList.contains("open")) {
    submenu.classList.remove("open");
    submenu.style.display = "none"; // Close
    parent.classList.remove("open");
  } else {
    submenu.classList.add("open");
    submenu.style.display = "block"; // Open
    parent.classList.add("open");
  }
}

// Regulator Chart
new Chart(document.getElementById("regulatorChart").getContext("2d"), {
    type: "bar",
    data: {
        labels: ["RBI", "FATF", "ISACA", "FICCI", "ISO"],
        datasets: [{
            label: "% Compliance",
            data: [80, 95, 85, 90, 60],
            backgroundColor: ["#e74c3c", "#8e44ad", "#2ecc71", "#3498db", "#c0392b"],
            barPercentage: 0.6,
            categoryPercentage: 0.8
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false
    }
});

// Controls Chart
new Chart(document.getElementById("controlsChart").getContext("2d"), {
    type: "doughnut",
    data: {
        labels: ["Compliant", "Partially Compliant", "Non Compliant"],
        datasets: [{
            data: [50, 30, 20],
            backgroundColor: ["#2ecc71", "#f1c40f", "#e74c3c"],
            borderWidth: 2,
            hoverOffset: 8,
            cutout: "70%"
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false
    }
});

// Pie Chart
new Chart(document.getElementById('pieChart').getContext('2d'), {
    type: 'pie',
    data: {
        labels: ['On Time', 'Delayed', 'Pending'],
        datasets: [{
            data: [60, 20, 20],
            backgroundColor: ['#17a2b8', '#ffc107', '#dc3545']
        }]
    },
    options: { responsive: true }
});

// Horizontal Bar Chart
new Chart(document.getElementById('barChart').getContext('2d'), {
    type: 'bar',
    data: {
        labels: [
            'Prudential Regulation', 'Operational Resilience', 'Financial Crime Prevention',
            'Conduct Regulation', 'Market Integrity', 'Reporting Requirements',
            'Fintech Framework', 'Risk Management', 'Consumer Protection',
            'IT Governance', 'Cybersecurity', 'Data Protection', 'Market Reforms'
        ],
        datasets: [{
            label: 'Compliance Score',
            data: [0.8, 0.9, 0.85, 0.7, 0.75, 0.6, 0.5, 0.7, 0.85, 0.9, 0.95, 0.9, 0.8],
            backgroundColor: '#673ab7'
        }]
    },
    options: { responsive: true, indexAxis: 'y' }
});


// Bar Chart 2
const barChart2Ctx = document.getElementById("barChart2").getContext('2d');
new Chart(barChart2Ctx, {
    type: 'bar',
    data: {
        labels: ["Control Effectiveness", "Compliance Rate", "Risk Mitigation Actions"],
        datasets: [{
            label: "Current Value",
            data: [85, 95, 70],
            backgroundColor: "#6a5acd"
        }]
    },
    options: {} // Empty options to prevent error
});

// Line Chart
const lineChartCtx = document.getElementById("lineChart").getContext('2d');
new Chart(lineChartCtx, {
    type: 'line',
    data: {
        labels: ["High-Risk Incidents", "Audit Finding Outstanding"],
        datasets: [{
            label: "Current Value",
            data: [6, 3],
            borderColor: "#6a5acd",
            fill: false
        }]
    },
    options: {} // Empty options to prevent error
});