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


// export 
function exportToCSV(sectionId) {
    // Get the table element by the section ID
    const table = document.querySelector(`#${sectionId} table`);
    
    if (!table) {
        alert("Table not found for this section.");
        return;
    }
    
    // Initialize an array to hold CSV data
    let csvData = [];
    
    // Loop through table rows and columns to collect the data
    const rows = table.rows;
    
    // Loop through table headers to add them to the CSV
    const headers = [];
    for (let i = 0; i < rows[0].cells.length; i++) {
        headers.push(rows[0].cells[i].textContent.trim());
    }
    csvData.push(headers.join(','));  // Add header to CSV data
    
    // Loop through table rows (excluding the header) and get the data
    for (let i = 1; i < rows.length; i++) {
        const rowData = [];
        for (let j = 0; j < rows[i].cells.length; j++) {
            rowData.push(rows[i].cells[j].textContent.trim());
        }
        csvData.push(rowData.join(','));
    }
    
    // Convert CSV data array to a string
    const csvString = csvData.join('\n');
    
    // Create a blob from the CSV string
    const blob = new Blob([csvString], { type: 'text/csv' });
    
    // Create a temporary link element
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${sectionId}_data.csv`;  // Set the filename based on sectionId
    link.click();  // Trigger the download
}



function showContent(id, event) {
    document.querySelectorAll('.content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(id).classList.add('active');

    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
    });
    event.target.classList.add('active');
}

function searchTable() {
    let input = document.querySelector(".search-box").value.toLowerCase();
    let rows = document.querySelectorAll("#complianceTable tbody tr");
    rows.forEach(row => {
        let text = row.textContent.toLowerCase();
        row.style.display = text.includes(input) ? "" : "none";
    });
}

function updateEntries() {
    let entries = document.getElementById("entries").value;
    paginateTable(entries);
}

function paginateTable(entries) {
    let table = document.getElementById("complianceTable");
    let rows = table.getElementsByTagName("tbody")[0].getElementsByTagName("tr");
    let pagination = document.getElementById("paginationDashboard1"); // Corrected ID
    pagination.innerHTML = "";
    let totalPages = Math.ceil(rows.length / entries);
    for (let i = 0; i < totalPages; i++) {
        let button = document.createElement("button");
        button.innerText = i + 1;
        button.onclick = function () { showPage(i, entries); };
        pagination.appendChild(button);
    }
    showPage(0, entries);
}

function showPage(page, entries) {
    let rows = document.querySelectorAll("#complianceTable tbody tr");
    rows.forEach((row, i) => {
        row.style.display = (i >= page * entries && i < (page + 1) * entries) ? "" : "none";
    });
}

window.onload = function() { updateEntries(); };

// Search Table (Generalized version)
function searchTableById(tableId, inputId) {
    var input = document.getElementById(inputId);
    var filter = input.value.toUpperCase();
    var table = document.getElementById(tableId);
    var tr = table.getElementsByTagName("tr");

    for (var i = 1; i < tr.length; i++) {
        var td = tr[i].getElementsByTagName("td")[0];
        if (td) {
            var txtValue = td.textContent || td.innerText;
            if (txtValue.toUpperCase().indexOf(filter) > -1) {
                tr[i].style.display = "";
            } else {
                tr[i].style.display = "none";
            }
        }
    }
}

// Chart for Compliance Status
const ctx = document.getElementById('complianceChart').getContext('2d');
new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ["CFO", "Operations Head", "IT Security Head", "Risk Manager", "Compliance Office"],
        datasets: [{
            label: "Current Compliance Status",
            data: [100, 90, 80, 75, 60],
            backgroundColor: 'blue'
        }]
    },
    options: {
        indexAxis: 'y',
        responsive: true,
        scales: {
            x: {
                beginAtZero: true,
                max: 120
            }
        }
    }
});

// Chart for Compliance Percentage
const complianceCtx = document.getElementById('statusChart').getContext('2d');
new Chart(complianceCtx, {
    type: 'bar',
    data: {
        labels: ['Companies Act', 'Cybersecurity Guidelines', 'Basel III Framework', 'Prevention of Money Laundering Act', 'Reserve Bank of India Guidelines'],
        datasets: [{
            label: 'Compliance Percentage',
            data: [98, 100, 85, 90, 95],
            backgroundColor: 'green'
        }]
    },
    options: {
        indexAxis: 'y',
        responsive: true,
        scales: {
            x: { beginAtZero: true, max: 100 }
        },
        plugins: {
            legend: { display: false }
        }
    }
});

// Compliance Breaches Chart (Stacked)
const breachesCtx = document.getElementById('breachChart').getContext('2d');
new Chart(breachesCtx, {
    type: 'bar',
    data: {
        labels: [
            'Minor non-compliance issues resolved',
            'Fully compliant',
            'Further improvements needed',
            'High risk areas identified',
            'On track, minor adjustments needed'
        ],
        datasets: [
            {
                label: 'No of high risk compliance breaches',
                data: [0, 0, 10, 15, 8],
                backgroundColor: 'purple'
            },
            {
                label: 'No of medium risk compliance breaches',
                data: [40, 0, 30, 25, 50],
                backgroundColor: 'orange'
            },
            {
                label: 'No of low risk compliance breaches',
                data: [0, 100, 60, 50, 42],
                backgroundColor: 'gray'
            }
        ]
    },
    options: {
        indexAxis: 'y',
        responsive: true,
        scales: {
            x: { beginAtZero: true, max: 100 }
        },
        plugins: {
            legend: { display: false }
        }
    }
});
