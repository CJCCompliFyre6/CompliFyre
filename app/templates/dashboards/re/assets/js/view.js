// Toggle Sidebar
function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
  const menuIcon = document.querySelector(".menu-icon i");

  if (menuIcon.classList.contains("bx-menu")) {
    menuIcon.classList.replace("bx-menu", "bx-x");
  } else {
    menuIcon.classList.replace("bx-x", "bx-menu");
  }
}

// Function to close the sidebar when clicking outside
function closeSidebarIfClickedOutside(event) {
  const sidebar = document.getElementById("sidebar");
  const menuIcon = document.querySelector(".menu-icon i");

  if (!sidebar.contains(event.target) && !menuIcon.contains(event.target)) {
    sidebar.classList.remove("open");
    menuIcon.classList.replace("bx-x", "bx-menu");
  }
}

// Add the event listener to close sidebar if clicking outside
document.addEventListener("click", closeSidebarIfClickedOutside);

function toggleSubmenu(event) {
  event.preventDefault();

  let parent = event.target.closest(".submenu");
  let submenu = parent.querySelector(".submenu-items");

  document.querySelectorAll(".submenu-items").forEach((item) => {
    if (item !== submenu) {
      item.classList.remove("open");
      item.style.display = "none";
      item.parentElement.classList.remove("open");
    }
  });

  if (submenu.classList.contains("open")) {
    submenu.classList.remove("open");
    submenu.style.display = "none";
    parent.classList.remove("open");
  } else {
    submenu.classList.add("open");
    submenu.style.display = "block";
    parent.classList.add("open");
  }
}

const searchInput = document.getElementById("searchInput");
const entriesSelect = document.getElementById("entriesSelect");
const table = document.getElementById("guidelinesTable");
const rows = table ? Array.from(table.querySelectorAll("tbody tr")) : [];
if (!table) { console.warn("guidelinesTable not found on this page — skipping table logic"); }
if (table) {
  const pagination = document.getElementById('pagination');
  let currentPage = 1;
  let entriesPerPage = entriesSelect ? parseInt(entriesSelect.value) : 10;

  function renderTable() {
    const start = (currentPage - 1) * entriesPerPage;
    const end = start + entriesPerPage;
    rows.forEach((row, index) => {
      row.style.display = index >= start && index < end ? '' : 'none';
    });
    renderPagination();
  }

  function renderPagination() {
    pagination.innerHTML = '';
    const totalPages = Math.ceil(rows.length / entriesPerPage);
    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement('button');
      btn.textContent = i;
      btn.className = i === currentPage ? 'active' : '';
      btn.addEventListener('click', () => { currentPage = i; renderTable(); });
      pagination.appendChild(btn);
    }
  }

  if (searchInput) searchInput.addEventListener('input', () => {
    const filter = searchInput.value.toLowerCase();
    rows.forEach((row) => {
      row.style.display = row.textContent.toLowerCase().includes(filter) ? '' : 'none';
    });
  });

  if (entriesSelect) entriesSelect.addEventListener('change', () => {
    entriesPerPage = parseInt(entriesSelect.value);
    currentPage = 1;
  });

}

function uploadFile() {
  let fileInput = document.getElementById("fileInput");
  let file = fileInput.files[0]; // Get the first selected file

  if (file) {
    document.getElementById("fileName").innerText =
      "Selected file: " + file.name;

    // If sending to a server:
    let formData = new FormData();
    formData.append("file", file);

    fetch("/upload-endpoint", {
      method: "POST",
      body: formData,
    })
      .then((response) => response.json())
      .then((data) => alert("File uploaded successfully!"))
      .catch((error) => alert("Error uploading file."));
  } else {
    alert("Please select a file first!");
  }
}

// Function to toggle the visibility of the dropdown content
function toggleDropdown2(element) {
  const dropdownContent = element
    .closest(".action-menu")
    .querySelector(".dropdown-content2");
  dropdownContent.classList.toggle("show"); // Toggle the 'show' class to display or hide the dropdown
}

// link shariing code
function openLinkSharingModal() {
  document.getElementById("linkSharingModal").style.display = "block";
}

function closeLinkSharingModal() {
  document.getElementById("linkSharingModal").style.display = "none";
}

function openUploadModal() {
  document.getElementById("uploadModal").style.display = "block";
}

function closeUploadModal() {
  document.getElementById("uploadModal").style.display = "none";
}

function openPromptModel() {
  document.getElementById("promptModal").style.display = "block";
}

function closepromptModal() {
  document.getElementById("promptModal").style.display = "none";
}

function submitLink(event) {
  event.preventDefault(); // Prevent default form submission
  var link = document.getElementById("shareableLink").value;
  console.log("Submitted Link:", link); // Replace with backend connection logic
  alert("Link submitted: " + link);
  closeLinkSharingModal();
}

window.onclick = function (event) {
  var modal = document.getElementById("linkSharingModal");
  if (event.target == modal) {
    modal.style.display = "none";
  }
};

function toggleDropdown(event) {
  event.preventDefault();
  let dropdownMenu = document.getElementById("dropdown-menu");
  dropdownMenu.style.display =
    dropdownMenu.style.display === "block" ? "none" : "block";
}

document.addEventListener("click", function (event) {
  let dropdownMenu = document.getElementById("dropdown-menu");
  let button = document.querySelector(".add-new-guideline-btn");
  if (button && dropdownMenu && !button.contains(event.target) && !dropdownMenu.contains(event.target)) {
    dropdownMenu.style.display = "none";
  }
});

function openLinkSharingModal() {
  document.getElementById("linkSharingModal").style.display = "block";
}
function closeLinkSharingModal() {
  document.getElementById("linkSharingModal").style.display = "none";
}
function submitLink(event) {
  event.preventDefault();
  alert("Link submitted: " + document.getElementById("shareableLink").value);
  closeLinkSharingModal();
}

function fetchPDFs(event) {
  event.preventDefault(); // Prevent default form submission
  var link = document.getElementById("shareableLink").value;
  console.log("Submitted Link:", link); // Replace with backend connection logic
  alert("Link submitted: " + link);
  closeLinkSharingModal();
}

window.onclick = function (event) {
  var modal = document.getElementById("linkSharingModal");
  if (event.target == modal) {
    modal.style.display = "none";
  }
};

function openLinkSharingModal() {
  document.getElementById("linkSharingModal").style.display = "block";
}

function closeLinkSharingModal() {
  document.getElementById("linkSharingModal").style.display = "none";
}

async function submitLink(event) {
  event.preventDefault(); // Prevent form submission from reloading the page

  const form = event.target;
  const linkValue = form.elements["shareableLink"].value; // Access input value

  console.log("Entered Link:", linkValue);

  var myHeaders = new Headers();
  myHeaders.append("Content-Type", "application/json");

  var raw = JSON.stringify({ url: linkValue });

  var requestOptions = {
    method: "POST",
    headers: myHeaders,
    body: raw,
    redirect: "follow",
  };
  document.getElementById("loadingIcon").style.display = "block";
  try {
    const response = await fetch("/api/download/scan", requestOptions);
    const result = await response.text(); // Convert response to text or JSON if applicable

    console.log("API Response:", result);

    // Store result in localStorage
    localStorage.setItem("apiResult", result);
    document.getElementById("loadingIcon").style.display = "none";
    // Redirect to link.html

    window.location.href = `/re/links`;
  } catch (error) {
    console.log("Error:", error);
  }
}

async function fetchPDFs(event) {
  event.preventDefault(); // Prevent form submission

  const urlInput = document.getElementById("shareableLink").value;

  if (!urlInput) {
    alert("Please enter a valid URL.");
    return;
  }

  try {
    // Fetch the HTML content from the given URL
    const response = await fetch(urlInput);
    const text = await response.text();

    // Create a temporary DOM to parse the content
    const parser = new DOMParser();
    const doc = parser.parseFromString(text, "text/html");

    // Extract all PDF links
    const links = doc.querySelectorAll("a[href$='.pdf']");
    const pdfLinks = Array.from(links).map((link) => link.href);

    // Display the PDFs in the table
    displayPDFs(pdfLinks);
  } catch (error) {
    console.error("Error fetching PDFs:", error);
    alert("Failed to fetch PDFs. Please check the URL and try again.");
  }
}

function fetchPDFs(event) {
  event.preventDefault(); // Prevent form submission

  const userUrl = document.getElementById("shareableLink").value;
  if (!userUrl) {
    alert("Please enter a valid URL!");
    return;
  }

  // API request
  const myHeaders = new Headers();
  myHeaders.append("Content-Type", "application/json");

  const raw = JSON.stringify({ url: userUrl });

  const requestOptions = {
    method: "POST",
    headers: myHeaders,
    body: raw,
    redirect: "follow",
  };

  fetch("/api/download/scan", requestOptions)
    .then((response) => response.json())
    .then((data) => {
      populateTable(data);
      closeLinkSharingModal(); // Close modal after fetching data
    })
    .catch((error) => console.error("Error fetching data:", error));
}

// Function to populate table with fetched data
function populateTable(data) {
  const tableBody = document.querySelector("#guidelinesTable tbody");
  tableBody.innerHTML = ""; // Clear existing rows

  data.forEach((item) => {
    const row = document.createElement("tr");

    // Title Column
    const titleCell = document.createElement("td");
    titleCell.textContent = item.title;
    row.appendChild(titleCell);

    // URL Column
    const urlCell = document.createElement("td");
    const urlLink = document.createElement("a");
    urlLink.href = item.url;
    urlLink.textContent = item.title;
    urlLink.target = "_blank";
    urlCell.appendChild(urlLink);
    row.appendChild(urlCell);

    // Download Button Column
    const downloadCell = document.createElement("td");
    const downloadLink = document.createElement("a");
    downloadLink.href = item.url;
    downloadLink.download = item.title;
    const downloadButton = document.createElement("button");
    downloadButton.textContent = "Download";
    downloadLink.appendChild(downloadButton);
    downloadCell.appendChild(downloadLink);
    row.appendChild(downloadCell);

    tableBody.appendChild(row);
  });
}

// Initialize taskNotifier when the page loads
document.addEventListener("DOMContentLoaded", function () {
  // Initialize the task notifier if it exists
  if (typeof TaskNotifier !== "undefined") {
    window.taskNotifier = new TaskNotifier();
  }
});
