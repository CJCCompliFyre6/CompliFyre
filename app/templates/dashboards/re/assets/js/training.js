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
  
///// *******************************pagination and entry box *************************/
let currentPage = 1;
let rowsPerPage = 10;
const tableBody = document.getElementById("tableBody");
const pageNumbers = document.getElementById("pageNumbers");
const selectEntries = document.getElementById("entriesSelect");

// Function to update table entries based on selected rows per page
function updateTableEntries() {
    rowsPerPage = parseInt(selectEntries.value);
    currentPage = 1; // Reset to first page when entries per page is changed
    displayTableRows();
}

// Function to display the table rows for the current page
function displayTableRows() {
    const rows = tableBody.getElementsByTagName("tr");
    const totalRows = rows.length;
    const totalPages = Math.ceil(totalRows / rowsPerPage);

    // Hide all rows initially
    for (let i = 0; i < totalRows; i++) {
        rows[i].style.display = "none";
    }

    // Show rows for the current page
    let start = (currentPage - 1) * rowsPerPage;
    let end = start + rowsPerPage;
    for (let i = start; i < end && i < totalRows; i++) {
        rows[i].style.display = "";
    }

    // Update pagination
    updatePagination(totalPages);
}

// Function to update pagination controls
function updatePagination(totalPages) {
    pageNumbers.innerHTML = "";

    for (let i = 1; i <= totalPages; i++) {
        const button = document.createElement("button");
        button.innerText = i;
        button.classList.add(i === currentPage ? "active" : "");
        button.onclick = () => {
            currentPage = i;
            displayTableRows();
        };
        pageNumbers.appendChild(button);
    }

    // Disable prev/next buttons on the first/last page
    document.getElementById("prevPageBtn").disabled = currentPage === 1;
    document.getElementById("nextPageBtn").disabled = currentPage === totalPages;
}

// Function to handle previous/next page buttons
function changePage(direction) {
    const rows = tableBody.getElementsByTagName("tr");
    const totalPages = Math.ceil(rows.length / rowsPerPage);

    if (direction === "prev" && currentPage > 1) {
        currentPage--;
    } else if (direction === "next" && currentPage < totalPages) {
        currentPage++;
    }

    displayTableRows();
}

// Run on page load
document.addEventListener("DOMContentLoaded", () => {
    displayTableRows();
});

  

//*********************search*******************/
  document.getElementById('searchInput').addEventListener('input', function() {
    let filter = this.value.toLowerCase();
    let rows = document.querySelectorAll('#tableBody tr');
    rows.forEach(row => {
        let text = row.textContent.toLowerCase();
        row.style.display = text.includes(filter) ? '' : 'none';
    });
});





//**************************************export*******************************/
// Function to export the table data to CSV
function exportToCSV() {
    // Get the table and the rows inside it
    const table = document.querySelector("table");
    const rows = table.querySelectorAll("tr");

    // Initialize an array to hold the CSV content
    let csvContent = "";

    // Loop through each row
    rows.forEach((row, index) => {
        // Get the columns (td or th) of the row
        const cols = row.querySelectorAll("td, th");
        const rowData = [];

        // Loop through each column and get the text content
        cols.forEach(col => {
            rowData.push(col.innerText);
        });

        // Join the row data into a CSV line and append it to csvContent
        csvContent += rowData.join(",") + "\n";
    });

    // Create a link element to trigger the download
    const link = document.createElement("a");
    link.href = "data:text/csv;charset=utf-8," + encodeURI(csvContent);
    link.target = "_blank";
    link.download = "training_data.csv"; // Set the filename for the CSV

    // Trigger the click event on the link to download the CSV file
    link.click();
}


document.addEventListener("DOMContentLoaded", function () {
    let ctx = document.getElementById("completionChart").getContext("2d");

    let completionChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: ["AML Training", "Cybersecurity Awareness", "Compliance Policies Overview"],
            datasets: [{
                label: "Completion Rate (%)",
                data: [90, 100, 80], // Data matching the table
                backgroundColor: ["#4CAF50", "#2196F3", "#FF9800"],
                borderColor: ["#388E3C", "#1976D2", "#F57C00"],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });
});
