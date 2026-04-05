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


// Tab Switching
function showTable() {
  document.getElementById('tableSection').style.display = 'block';
  document.getElementById('chartSection').style.display = 'none';
  
  // Update the tab buttons
  document.querySelector('.tabs button.active').classList.remove('active');
  event.target.classList.add('active');
}

function showChart() {
  document.getElementById('tableSection').style.display = 'none';
  document.getElementById('chartSection').style.display = 'block';
  
  // Update the tab buttons
  document.querySelector('.tabs button.active').classList.remove('active');
  event.target.classList.add('active');
}



// Pagination variables
let currentPage = 1;
let rowsPerPage = 5;  // Default value of rows per page

// Function to render the table with pagination
function renderTable() {
  const tableBody = document.getElementById("auditTableBody");
  const rows = tableBody.getElementsByTagName("tr");
  const start = (currentPage - 1) * rowsPerPage;
  const end = start + rowsPerPage;

  // Hide all rows initially
  for (let row of rows) {
    row.style.display = "none";
  }

  // Show rows for the current page
  for (let i = start; i < end && i < rows.length; i++) {
    rows[i].style.display = "";
  }

  renderPagination(rows.length);
}

// Function to render the pagination buttons
function renderPagination(totalRows) {
  const pagination = document.getElementById("pagination");
  const totalPages = Math.ceil(totalRows / rowsPerPage);

  // Clear the existing pagination
  pagination.innerHTML = '';

  // Create page number buttons
  for (let i = 1; i <= totalPages; i++) {
    const pageButton = document.createElement("button");
    pageButton.innerHTML = i;
    pageButton.className = (i === currentPage) ? 'active' : '';
    pageButton.onclick = function() {
      currentPage = i;
      renderTable();
    };
    pagination.appendChild(pageButton);
  }
}

// Function to change the number of rows displayed
function changeEntries() {
  const entriesSelect = document.getElementById("entriesSelect");
  rowsPerPage = parseInt(entriesSelect.value);
  currentPage = 1;  // Reset to the first page
  renderTable();
}

// Initialize the table and pagination
window.onload = function() {
  renderTable();
  document.getElementById("entriesSelect").addEventListener("change", changeEntries);
};

// Search function
document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("search");
    const tableBody = document.getElementById("auditTableBody");
    const rows = tableBody.getElementsByTagName("tr");

    searchInput.addEventListener("keyup", function () {
        const query = searchInput.value.toLowerCase();

        for (let row of rows) {
            let text = row.textContent.toLowerCase();
            row.style.display = text.includes(query) ? "" : "none";
        }
    });
});

// Export function
function exportToCSV() {
    let csv = "Audit Finding ID,Regulation Affected,Finding Description,Date Identified,Risk Category,Remediation Status,Owner,Date\n";
    let rows = document.querySelectorAll('#auditTableBody tr');
    rows.forEach(row => {
        let cols = row.querySelectorAll('td');
        let data = [];
        cols.forEach(col => data.push(col.innerText));
        csv += data.join(',') + "\n";
    });
    let blob = new Blob([csv], { type: 'text/csv' });
    let a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'audit_findings.csv';
    a.click();
}

// Chart initialization
const ctx1 = document.getElementById('chart1').getContext('2d');
new Chart(ctx1, {
    type: 'bar',
    data: {
        labels: ['RBI Cybersecurity Guidelines', 'RBI Prudential IRAC Norms', 'Companies Act'],
        datasets: [
            { label: 'In Progress', data: [2, 3, 1], backgroundColor: 'blue' },
            { label: 'Resolved', data: [2, 2, 3], backgroundColor: 'orange' },
            { label: 'Not Started', data: [2, 2, 1], backgroundColor: 'gray' }
        ]
    },
    options: {
        responsive: true,
        scales: {
            x: {
                ticks: {
                    autoSkip: false,
                    maxRotation: 0,
                    minRotation: 0
                }
            }
        }
    }
});

const ctx2 = document.getElementById('chart2').getContext('2d');
new Chart(ctx2, {
    type: 'bar',
    data: {
        labels: ['In Progress', 'Resolved', 'Not Started'],
        datasets: [{
            label: 'Grand Total',
            data: [6, 7, 5],
            backgroundColor: ['blue', 'orange', 'gray']
        }]
    },
    options: {
        responsive: true,
        scales: {
            x: {
                ticks: {
                    autoSkip: false,
                    maxRotation: 0,
                    minRotation: 0
                }
            }
        }
    }
});
