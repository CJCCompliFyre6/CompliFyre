#!/usr/bin/env python3
"""
Load the reviewed BFSI regulator inventory (29 rows, 13 regulators/bodies)
into the real RegulatoryBodies table on staging, replacing existing test
data (RBI + SIDBI from earlier tonight -- SIDBI re-included in this load).

Rebuilt from scratch after unexplained extra rows were found in an earlier
version of the source spreadsheet -- every row in THIS version was
individually re-verified against the actual conversation history before
this script was generated.

Run this INSIDE flask shell (needs db, RegulatoryBodies already in scope).
"""

REGULATOR_DATA = [
    ('Reserve Bank of India', 'Master Directions (category listing)', 'India', 'Banking, NBFC, Payment Systems, Financial Markets', 'Banks, NBFCs, Payment System Operators, Standalone Primary Dealers', 'https://www.rbi.org.in/Scripts/BS_ViewMasterDirections.aspx'),
    ('Reserve Bank of India', 'Master Circulars (category listing)', 'India', 'Banking, NBFC, Payment Systems, Financial Markets', 'Banks, NBFCs, Payment System Operators, Standalone Primary Dealers', 'https://www.rbi.org.in/Scripts/BS_ViewMasterCirculars.aspx'),
    ('Reserve Bank of India', 'Notifications (category listing)', 'India', 'Banking, NBFC, Payment Systems, Financial Markets', 'Banks, NBFCs, Payment System Operators, Standalone Primary Dealers', 'https://www.rbi.org.in/Scripts/NotificationUser.aspx'),
    ('Reserve Bank of India', 'Draft Notifications / Guidelines (category listing)', 'India', 'Banking, NBFC, Payment Systems, Financial Markets', 'Banks, NBFCs, Payment System Operators, Standalone Primary Dealers', 'https://rbi.org.in/Scripts/DraftNotificationsGuildelines.aspx'),
    ('Reserve Bank of India', 'Standalone Circulars (category listing)', 'India', 'Banking, NBFC, Payment Systems, Financial Markets', 'Banks, NBFCs, Payment System Operators, Standalone Primary Dealers', 'https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx'),
    ('Securities and Exchange Board of India (SEBI)', 'Circulars', 'India', 'Capital Markets, Securities, Mutual Funds, AIFs', 'Stock Exchanges, Brokers, Depositories, Mutual Funds, AIFs, Merchant Bankers, Credit Rating Agencies', 'https://www.sebi.gov.in/legal/circulars.html'),
    ('Securities and Exchange Board of India (SEBI)', 'Master Circulars', 'India', 'Capital Markets, Securities, Mutual Funds, AIFs', 'Stock Exchanges, Brokers, Depositories, Mutual Funds, AIFs, Merchant Bankers, Credit Rating Agencies', 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=6&smid=0'),
    ('Securities and Exchange Board of India (SEBI)', 'Regulations', 'India', 'Capital Markets, Securities, Mutual Funds, AIFs', 'Stock Exchanges, Brokers, Depositories, Mutual Funds, AIFs, Merchant Bankers, Credit Rating Agencies', 'https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=3&smid=0'),
    ('Insurance Regulatory and Development Authority of India (IRDAI)', 'Circulars', 'India', 'Insurance', 'Life Insurers, General Insurers, Insurance Intermediaries, Insurance Repositories', 'https://irdai.gov.in/circulars'),
    ('Insurance Regulatory and Development Authority of India (IRDAI)', 'Notifications', 'India', 'Insurance', 'Life Insurers, General Insurers, Insurance Intermediaries, Insurance Repositories', 'https://irdai.gov.in/notifications'),
    ('Insurance Regulatory and Development Authority of India (IRDAI)', 'Guidelines', 'India', 'Insurance', 'Life Insurers, General Insurers, Insurance Intermediaries, Insurance Repositories', 'https://irdai.gov.in/guidelines'),
    ('Insurance Regulatory and Development Authority of India (IRDAI)', 'Orders', 'India', 'Insurance', 'Life Insurers, General Insurers, Insurance Intermediaries, Insurance Repositories', 'https://irdai.gov.in/orders1'),
    ('Pension Fund Regulatory and Development Authority (PFRDA)', 'Active Circulars', 'India', 'Pension Funds, National Pension System', 'Pension Funds, NPS Trust, CRA, Custodian, POP, Annuity Service Providers', 'https://pfrda.org.in/regulatory-framework/circulars/active-circulars'),
    ('Pension Fund Regulatory and Development Authority (PFRDA)', 'Active Master Circulars', 'India', 'Pension Funds, National Pension System', 'Pension Funds, NPS Trust, CRA, Custodian, POP, Annuity Service Providers', 'https://pfrda.org.in/regulatory-framework/master-circulars/active-master-circulars'),
    ('Pension Fund Regulatory and Development Authority (PFRDA)', 'Guidelines', 'India', 'Pension Funds, National Pension System', 'Pension Funds, NPS Trust, CRA, Custodian, POP, Annuity Service Providers', 'https://pfrda.org.in/regulatory-framework/guidelines'),
    ('Pension Fund Regulatory and Development Authority (PFRDA)', 'Regulations', 'India', 'Pension Funds, National Pension System', 'Pension Funds, NPS Trust, CRA, Custodian, POP, Annuity Service Providers', 'https://pfrda.org.in/regulatory-framework/regulations'),
    ('Insolvency and Bankruptcy Board of India (IBBI)', 'Circulars', 'India', 'Insolvency, Bankruptcy, Corporate Recovery', 'Insolvency Professionals, Insolvency Professional Agencies, Insolvency Professional Entities, Information Utilities, Registered Valuers', 'https://ibbi.gov.in/search/index/circulars'),
    ('National Bank for Agriculture and Rural Development (NABARD)', 'Circulars', 'India', 'Rural and Agricultural Credit, Cooperative Banking', 'Regional Rural Banks (RRBs), State Cooperative Banks, District Central Cooperative Banks', 'https://www.nabard.org/circulars.aspx?cid=504&id=24'),
    ('Financial Intelligence Unit - India (FIU-IND)', 'Notices / Home', 'India', 'AML/CFT, Money Laundering Prevention', 'Banks, NBFCs, Insurance Companies, Payment System Operators, Virtual Digital Asset Service Providers, all PMLA Reporting Entities', 'https://fiuindia.gov.in/'),
    ('Indian Computer Emergency Response Team (CERT-In)', 'Advisories', 'India', 'Cybersecurity (cross-sector)', 'All body corporates, service providers, intermediaries, data centres (includes all BFSI entities)', 'https://www.cert-in.org.in/s2cMainServlet?pageid=PUBADVLIST'),
    ('Small Industries Development Bank of India (SIDBI)', 'Circulars listing', 'India', 'MSME Financing, Micro/Small/Medium Enterprise Development', 'Banks, Small Finance Banks, NBFCs, MFIs, Fintechs', 'https://www.sidbi.in/en/circulars'),
    ('National Housing Bank (NHB)', 'Notifications / Publications', 'India', 'Housing Finance (refinance/development role only)', 'Housing Finance Companies (refinance relationship only, NOT regulatory)', 'https://www.nhb.org.in/'),
    ('Ministry of Corporate Affairs (MCA)', 'Notices & Circulars', 'India', 'Corporate Law, Companies Act Compliance', 'All Companies and LLPs registered under the Companies Act 2013, including NBFCs/HFCs in their capacity as companies', 'https://www.mca.gov.in/MinistryV2/noticeandcircular.html'),
    ('Ministry of Electronics and Information Technology (MeitY)', 'Data Protection Framework (DPDP Act/Rules)', 'India', 'Data Protection, Digital Personal Data', 'All Data Fiduciaries and Significant Data Fiduciaries -- includes banks, NBFCs, insurers, and all BFSI entities processing personal data', 'https://www.meity.gov.in/data-protection-framework'),
    ('International Financial Services Centres Authority (IFSCA)', 'Circulars', 'India (GIFT City IFSC)', 'Banking, Insurance, Capital Markets, Fund Management, Fintech, Aircraft/Ship Leasing', 'IFSC Banking Units, Insurance Offices (IIO/IIIO), Capital Market Intermediaries, Fund Management Entities, Finance Companies, Payment Service Providers, TechFin/FinTech entities', 'https://ifsca.gov.in/Legal/Index/wF6kttc1JR8='),
    ('International Financial Services Centres Authority (IFSCA)', 'Regulations', 'India (GIFT City IFSC)', 'Banking, Insurance, Capital Markets, Fund Management, Fintech, Aircraft/Ship Leasing', 'IFSC Banking Units, Insurance Offices (IIO/IIIO), Capital Market Intermediaries, Fund Management Entities, Finance Companies, Payment Service Providers, TechFin/FinTech entities', 'https://ifsca.gov.in/Legal/Index/ogGPf3wx5GE='),
    ('International Financial Services Centres Authority (IFSCA)', 'Notifications', 'India (GIFT City IFSC)', 'Banking, Insurance, Capital Markets, Fund Management, Fintech, Aircraft/Ship Leasing', 'IFSC Banking Units, Insurance Offices (IIO/IIIO), Capital Market Intermediaries, Fund Management Entities, Finance Companies, Payment Service Providers, TechFin/FinTech entities', 'https://ifsca.gov.in/Legal/Index/zcGvy-Iqfcg='),
    ('International Financial Services Centres Authority (IFSCA)', 'Guidelines', 'India (GIFT City IFSC)', 'Banking, Insurance, Capital Markets, Fund Management, Fintech, Aircraft/Ship Leasing', 'IFSC Banking Units, Insurance Offices (IIO/IIIO), Capital Market Intermediaries, Fund Management Entities, Finance Companies, Payment Service Providers, TechFin/FinTech entities', 'https://ifsca.gov.in/Legal/Index/mizvnmwVAgs='),
    ('International Financial Services Centres Authority (IFSCA)', 'AML, CFT and KYC Compliance', 'India (GIFT City IFSC)', 'Banking, Insurance, Capital Markets, Fund Management, Fintech, Aircraft/Ship Leasing', 'IFSC Banking Units, Insurance Offices (IIO/IIIO), Capital Market Intermediaries, Fund Management Entities, Finance Companies, Payment Service Providers, TechFin/FinTech entities', 'https://ifsca.gov.in/Legal/Index/TCce8MyOmco='),
]

print(f"Deleting existing RegulatoryBodies rows...")
existing_count = RegulatoryBodies.query.count()
print(f"Found {existing_count} existing rows.")
RegulatoryBodies.query.delete()
db.session.commit()
print("Deleted.")

print(f"Inserting {len(REGULATOR_DATA)} new rows...")
for name, desc, geo, ind, gov, url in REGULATOR_DATA:
    r = RegulatoryBodies(name=name, description=desc, geography=geo, industry=ind, governed_institutions=gov, website_url=url)
    db.session.add(r)
db.session.commit()

final_count = RegulatoryBodies.query.count()
print(f"Done. RegulatoryBodies now has {final_count} rows (expected {len(REGULATOR_DATA)}).")