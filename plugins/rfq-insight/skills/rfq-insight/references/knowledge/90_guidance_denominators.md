# AVL Guidance Document — official Opportunity Info vocabulary

Generated from `Guidance Document.xlsx` by `Backlog/tests/tools/build_guidance.py`. Do not edit by hand.

Copy every value below character for character into the `opportunity` object. Never invent, shorten, merge or translate a value.

## Project type

Exactly one value.

| Project type | Description |
|---|---|
| Advanced / Pre-Development | Feasibility studies, market studies, concept investigations, Gen.0 system/component development (prior to Product Dev.) |
| TaaS (Testing as a Service) | Testing as a Service only, without engineering scope |
| Resident Engineering | Resident engineers, on-site (at customer´s premises) |
| SOP Project w/o CSM (up to SOP or partial SOP development) | Product Development up to SOP or partial SOP development, incl. release recommendation for AVL Development scope, without Component Supplier Management (CSM) (e.g. SW/controls development, calibration projects) |
| SOP Project with CSM (Turn Key Project) | Product Development up to SOP or partial SOP development, incl. release recommendation for AVL Development scope, including full component responsibility with Component Supplier Management (CSM) |
| Others | e.g. DRIVE/VSM/EPOS, Tippelmann test beds, certification and homologation, manufacturing, benchmarking… |

## Lead product

For every Master Opportunity one of the “Products” shall be selected as “Lead Product”: The “Lead Product” is the dominant enabler for the project (customer view). The Lead Product does not necessarily have to be the product with the highest percentage, but must (of course) be among the chosen products (≥ 5%).

Exactly one value from the Products (%) list below, and it must be one of the products you list with at least 5%.

## Technology

Exactly one value.

| Technology | Description |
|---|---|
| ICE & Mild Hybrid | Conventional powertrain incl. Micro Hybrid (Start/Stop and smart charging) and Mild Hybrid (capable of regenerative brake and torque assist/boost). |
| CO2-neutral ICE | Internal combustion engine designed primarily for operation with renewable fuels (e.g. H2, NH3, e-Fuel, methanol etc). |
| Hybrid | Capable of pure electric driving (Full Hybrid, PHEV). |
| Battery Electric | Battery Electric Vehicle or any other application of batteries, incl. stationary energy storage systems. |
| FC & EC | Fuel Cell and Electrolyzer Cell applications, either in vehicle or for stationary application, Power-to-Liquid applications. |
| ADAS | Scope of services/deliveries is mainly ADAS (powertrain type is irrelevant) |
| Other Green Tech. | Technology that contributes to reduction of CO2 and other GHG emissions, brake particle emissions, to reduced environmental impact of the product/service (resource requirements, recyclability etc.). Excluded: Development of conventional powertrain system, exhaust aftertreatment systems etc à must be allocated to Technology “ICE & Mild Hybrid” |
| Non-green Tech. | Non-CO2-neutral or with no explicit impact on reduction of GHG emission and/or improving environmental sustainability |

## Industry

Exactly one value.

| Industry | SAP Profit Center | Description |
|---|---|---|
| Passenger Car | A | •Passenger Car applications |
| 2-Wheeler | A | •Motorcycles, any kind of 2-wheeler vehicles |
| Racing | A | •Racing, regardless of powertrain and vehicle type |
| Truck & Bus | B | •Truck and Bus applications and LDT (engine test bed certified) |
| Off-Road | G | •Agricultural industry, construction machinery, mining, material handling (forklifts etc), mobile working machines (sweepers etc) |
| Special Purpose | G | •Defense and dual use applications |
| Hydrogen & Industrial Energy | G | •Industrial Energy – fuel cell power generation and hydrogen/e-Fuel production via electrolysis, stationary batteries, industrial applications (incl. CHP) |
| Marine, Rail | G | •Marine – ICE, fuel cell, battery, E-machine & Power Electronics, vehicle and PT integration, •railway applications |
| Aviation | G | •Aviation applications (consider Technology Readiness Level) |
| Others | O | •Manufacturing •Certification/homologation for all types of vehicles/products •Others |

## Products (%)

Share of AVL's development effort per product. Whole percentages that must add up to exactly 100. List only products with more than 0%.

| Product | Description |
|---|---|
| Chassis & Vehicle Motion | Chassis and Vehicle Motion refers to all engineering activities for the sub-systems and components that contribute to the vehicle's dynamics, safety, comfort and driving experience: 1.Tires & Wheels, 2. Suspension System (spring-damper systems, control arms, bushings, and kinematics), 3. Steering System (EPS, SbW, RWS), 4.Braking System (Hydraulic and electronic brake systems (ABS, ESC, brake-by-wire) and 5. Vehicle Motion Control (central vehicle motion control/coordination, AWD, torque vectoring, ESC, TC, RWS, active suspension). |
| Vehicle Development and Integration | Complete vehicle development, powertrain and system in vehicle integration, demonstrator vehicles, platform development support, geometrical configuration, body, safety (active and passive), homologation, NVH, aerodynamics, vehicle benchmarking etc. |
| Thermal Management and HVAC | Thermal Management and HVAC (Heating, Ventilation, Air Conditioning) of/for vehicles. → THM comprises e.g.: system design, component specification and supplier management, packaging→ Thermal Benchmarking → Thermal & Comfort Control Software → SOP development does e.g. not include: thermal management of powertrain components - such scope must be allocated to respective IC Based and Electrification Products |
| E/E Systems (incl Cyber Security & Safety) | HV and LV electric and electronics incl. software, functional safety, cyber security, infotainment, telematics, comfort electronics, wiring harness, EMC, data and network architecture, function architecture, wiring architecture and harness components, EE systems and related EE testing / EE simulation |
| ADAS / Automated Driving (incl. Connectivity) | Complete system, software, hardware, sensors (requirements engineering, system design, development, integration and validation) and connectivity |
| SW-Products (e.g. DRIVE, VSM, EPOS) | e.g. AVL-DRIVE (incl. Hardware), VSM, EPOS |
| Spark Ignited | Spark Ignited engines (Gasoline, H2, e-Fuels, etc) incl. engines for Hybrid powertrains, including embedded software |
| Compression Ignited | Compression Ignited engines (Diesel, NH3, e-Fuels etc) incl. engines for Hybrid powertrains, including embedded software |
| Powertrain System Integration, incl. Hybrid Powertrains | Development of Hybrid-Electric and Conventional Powertrains covering System Design (i.e. Requirement Engineering and System Specification), System Integration (i.e. functional, electrical and mechanical integration of all powertrain components) and System Calibration (i.e. Calibration of central powertrain controller) as well as Powertrain System Verification & Validation on Integration Test Instances (PAVIL and in Vehicle) |
| Transmission incl. Hybrid Transmission | Transmission incl. Hybrid Transmissions (DHT, AMT, AT, DCT, CVT, …….) |
| BEV Transmission and EDU / E-Axles | Transmissions and E-axles / Electric Drive Units Note: Please assign E-Machine and Power Electronic development share to “EM” |
| Powertrain System Integration BEV | Development of High Voltage Powertrains for Fuel Cell and Battery electric powertrains covering System Design (i.e. Requirement Engineering and System Specification), System Integration (i.e. functional, electrical and mechanical integration of all powertrain and all High Voltage components) and System Calibration (i.e. Calibration of central powertrain controller) as well as HV Powertrain System Verification & Validation on Integration Test Instances (HV Integration Test Bed, PAVIL and in Vehicle) |
| E-machine & Power Electronics | E-Machine & Power Electronics (incl. On Board Chargers) incl. their integration |
| Battery | Battery, BMS, including embedded software |
| Fuel Cell | PEM and Solid Oxide Fuel Cell - including embedded software |
| Electrolyzer | PEM, SOEC, AEL, AEM Electrolyzers, e-fuel and hydrogen derivates - including embedded software |
| Emerging Energy Technologies | Carbon Capture, Low Carbon Hydrogen, Stationary Energy Storage, Smart Grid Integration, Solar Water Splitting, non-Hydrogen Energy Technologies - including embedded software |
| Others (Testing facility Rentals, Manufacturing, etc) | Testing facility Rentals, Manufacturing, certification and homologation @ MTC, test equipment @ Tippelmann |

## Skills (%)

Share of AVL's effort per skill. Whole percentages that must add up to exactly 100. List only skills with more than 0%. These are NOT the tech-center skill areas in 80_avl_nomenclature_and_skill_areas.md.

| Skill | Abbr. | Description |
|---|---|---|
| Functional Development | FD | Functional system design, system integration and system verification on vehicle level, powertrain and other vehicle systems and all Elements like ICE, Fuel Cell, EDU, Battery, etc.. including generation of system specifications, requirements engineering and management, system simulation and definition of functional verification test, planning and execution / analysis. |
| Simulation | SA | Simulations on component, system or vehicle level… for all products |
| Design | DI | all design activities for all products |
| Software & Controls, E/E | SW | any kind of controls and E/E development for all products |
| Verification, Validation, Reliability & Industrialization (ickl. BIC) | VVR | All hardware related development activities for product verification (incl. mechanical development), validation (incl. durability testing) and reliability (incl. load matrix methodology) for all elements, powertrain and vehicle level. DVP definition, coordination and consulting and component engineering, production engineering; cost engineering and supply chain management activities for all products incl. in Battery Innovation Center |
| Calibration | CAL | Target-oriented adjustment of all parameters in all control units; for all functions, all mobility products, all technologies; on powertrain and vehicle level |
| Test Factory & Testing | TFT | all test facilities, measurement devices and operators. Including test planning & evaluation and logistics |
| Project Management | PJM | project and part project management including assistants |
| External Purchases (services, material, fuel, travel…) | EXP | services, material, fuel, travel |
| Manufacturing | MAN | Manufacturing |
