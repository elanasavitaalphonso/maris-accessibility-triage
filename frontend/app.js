/* ==================================================
   MARIS
   FINAL FRONTEND APPLICATION
================================================== */


const state = {
    jobId: null,
    url: "",
    statusTimer: null,

    documents: [],
    families: [],

    actionCounts: {},
    selectedAction: null,

    stopRequested: false
};


const ACTION_ORDER = [
    "Convert to HTML",
    "Convert to Web Form",
    "Fix Source & Re-export",
    "Remediate PDF",
    "Specialist Review",
    "Keep / Review",
    "External Owner Review"
];


const ACTION_DESCRIPTIONS = {
    "Convert to HTML":
        "Publish informational content directly on the web.",

    "Convert to Web Form":
        "Replace the PDF workflow with an accessible web form when practical.",

    "Fix Source & Re-export":
        "Correct accessibility in the original source file and export a new PDF.",

    "Remediate PDF":
        "Keep the PDF and repair accessibility directly in the document.",

    "Specialist Review":
        "Human judgment is needed before selecting the safest remediation pathway.",

    "Keep / Review":
        "The PDF may have a legitimate reason to remain, but accessibility still needs review.",

    "External Owner Review":
        "Confirm accessibility responsibility with the external document owner."
};


/* ==================================================
   DOM
================================================== */

const landingView =
    document.getElementById("landingView");

const scanningView =
    document.getElementById("scanningView");

const resultsView =
    document.getElementById("resultsView");


const scanForm =
    document.getElementById("scanForm");

const websiteUrl =
    document.getElementById("websiteUrl");

const landingError =
    document.getElementById("landingError");


const scanningDomain =
    document.getElementById("scanningDomain");

const scanStageLabel =
    document.getElementById("scanStageLabel");

const pagesVisited =
    document.getElementById("pagesVisited");

const pdfsFound =
    document.getElementById("pdfsFound");

const progressPercent =
    document.getElementById("progressPercent");

const progressFill =
    document.getElementById("progressFill");

const progressBar =
    document.getElementById("progressBar");

const currentDocument =
    document.getElementById("currentDocument");

const scanError =
    document.getElementById("scanError");


const stopScanArea =
    document.getElementById("stopScanArea");

const stopAnalyzeButton =
    document.getElementById("stopAnalyzeButton");

const stopScanHint =
    document.getElementById("stopScanHint");


const resultsDomain =
    document.getElementById("resultsDomain");

const resultsMeta =
    document.getElementById("resultsMeta");

const totalDocuments =
    document.getElementById("totalDocuments");

const familyCount =
    document.getElementById("familyCount");

const formCount =
    document.getElementById("formCount");


const actionSummaryGrid =
    document.getElementById("actionSummaryGrid");

const actionFilterList =
    document.getElementById("actionFilterList");

const selectedActionHeading =
    document.getElementById("selectedActionHeading");

const actionResults =
    document.getElementById("actionResults");


const familyResults =
    document.getElementById("familyResults");

const allDocuments =
    document.getElementById("allDocuments");

const documentSearch =
    document.getElementById("documentSearch");


const newScanButton =
    document.getElementById("newScanButton");

const newScanHeaderButton =
    document.getElementById("newScanHeaderButton");


/* ==================================================
   VIEW HELPERS
================================================== */

function showView(name) {

    landingView.classList.add("hidden");
    scanningView.classList.add("hidden");
    resultsView.classList.add("hidden");


    if (name === "landing") {

        landingView.classList.remove("hidden");

        newScanHeaderButton.classList.add(
            "hidden"
        );
    }


    if (name === "scanning") {

        scanningView.classList.remove(
            "hidden"
        );

        newScanHeaderButton.classList.remove(
            "hidden"
        );
    }


    if (name === "results") {

        resultsView.classList.remove(
            "hidden"
        );

        newScanHeaderButton.classList.remove(
            "hidden"
        );
    }


    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


function resetApp() {

    if (state.statusTimer) {

        clearInterval(
            state.statusTimer
        );
    }


    state.jobId = null;
    state.url = "";

    state.documents = [];
    state.families = [];

    state.actionCounts = {};
    state.selectedAction = null;

    state.stopRequested = false;


    websiteUrl.value = "";

    documentSearch.value = "";


    landingError.textContent = "";
    landingError.classList.add("hidden");

    scanError.textContent = "";
    scanError.classList.add("hidden");


    stopScanArea.classList.add("hidden");

    stopAnalyzeButton.disabled = false;

    stopAnalyzeButton.textContent =
        "Stop & analyze PDFs found so far";

    stopScanHint.textContent =
        "Stops discovery only. PDFs already found will still be analyzed.";


    showView("landing");
}


/* ==================================================
   START SCAN
================================================== */

scanForm.addEventListener(
    "submit",
    async (event) => {

        event.preventDefault();


        const url =
            websiteUrl.value.trim();


        if (!url) {

            landingError.textContent =
                "Enter a website URL.";

            landingError.classList.remove(
                "hidden"
            );

            return;
        }


        landingError.classList.add(
            "hidden"
        );


        try {

            const response =
                await fetch(
                    "/api/scan",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                url
                            })
                    }
                );


            if (!response.ok) {

                const data =
                    await safeJson(
                        response
                    );

                throw new Error(
                    data.detail ||
                    "Could not start scan."
                );
            }


            const data =
                await response.json();


            state.jobId =
                data.job_id;

            state.url =
                normalizeDisplayUrl(
                    url
                );

            state.stopRequested =
                false;


            scanningDomain.textContent =
                state.url;


            updateProgress({
                progress: 0,
                pages_visited: 0,
                pdfs_found: 0,
                stage: "queued",
                stage_label:
                    "Preparing scan"
            });


            showView(
                "scanning"
            );


            startStatusPolling();

        }

        catch (error) {

            landingError.textContent =
                error.message;

            landingError.classList.remove(
                "hidden"
            );
        }
    }
);


/* ==================================================
   STOP DISCOVERY
================================================== */

stopAnalyzeButton.addEventListener(
    "click",
    async () => {

        if (
            !state.jobId ||
            state.stopRequested
        ) {
            return;
        }


        state.stopRequested =
            true;


        stopAnalyzeButton.disabled =
            true;

        stopAnalyzeButton.textContent =
            "Stopping discovery…";

        stopScanHint.textContent =
            "Finishing the current page, then Maris will analyze the PDFs already found.";


        try {

            const response =
                await fetch(
                    `/api/scan/${state.jobId}/stop`,
                    {
                        method: "POST"
                    }
                );


            if (!response.ok) {

                const data =
                    await safeJson(
                        response
                    );

                throw new Error(
                    data.detail ||
                    "Could not stop discovery."
                );
            }


            const data =
                await response.json();


            const count =
                data.pdfs_found || 0;


            stopAnalyzeButton.textContent =
                `Analyzing ${count} PDF${count === 1 ? "" : "s"} found so far…`;

        }

        catch (error) {

            state.stopRequested =
                false;


            stopAnalyzeButton.disabled =
                false;

            stopAnalyzeButton.textContent =
                "Stop & analyze PDFs found so far";

            stopScanHint.textContent =
                error.message;
        }
    }
);


/* ==================================================
   STATUS POLLING
================================================== */

function startStatusPolling() {

    if (state.statusTimer) {

        clearInterval(
            state.statusTimer
        );
    }


    pollStatus();


    state.statusTimer =
        setInterval(
            pollStatus,
            1000
        );
}


async function pollStatus() {

    if (!state.jobId) {
        return;
    }


    try {

        const response =
            await fetch(
                `/api/scan/${state.jobId}`
            );


        if (!response.ok) {

            throw new Error(
                "Could not retrieve scan status."
            );
        }


        const data =
            await response.json();


        updateProgress(
            data
        );


        if (
            data.status === "complete"
        ) {

            clearInterval(
                state.statusTimer
            );

            state.statusTimer = null;


            await loadResults();

            return;
        }


        if (
            data.status === "error"
        ) {

            clearInterval(
                state.statusTimer
            );

            state.statusTimer = null;


            scanError.textContent =
                data.error ||
                "The scan failed.";

            scanError.classList.remove(
                "hidden"
            );
        }

    }

    catch (error) {

        clearInterval(
            state.statusTimer
        );

        state.statusTimer = null;


        scanError.textContent =
            error.message;

        scanError.classList.remove(
            "hidden"
        );
    }
}


/* ==================================================
   PROGRESS
================================================== */

function updateProgress(data) {

    const progress =
        Number(
            data.progress || 0
        );


    const pageCount =
        Number(
            data.pages_visited || 0
        );


    const pdfCount =
        Number(
            data.pdfs_found || 0
        );


    pagesVisited.textContent =
        pageCount;

    pdfsFound.textContent =
        pdfCount;


    progressPercent.textContent =
        `${progress}%`;

    progressFill.style.width =
        `${progress}%`;


    progressBar.setAttribute(
        "aria-valuenow",
        String(progress)
    );


    scanStageLabel.textContent =
        data.stage_label ||
        "Working";


    if (
        data.current_document
    ) {

        currentDocument.textContent =
            `Analyzing: ${data.current_document}`;

    }

    else if (
        data.ai_stage_label
    ) {

        currentDocument.textContent =
            data.ai_stage_label;

    }

    else {

        currentDocument.textContent =
            "";
    }


    updatePipeline(
        data.stage
    );


    updateStopButton(
        data,
        pdfCount
    );
}


function updateStopButton(
    data,
    pdfCount
) {

    const isDiscovering =
        data.stage ===
        "discovering";


    if (!isDiscovering) {

        stopScanArea.classList.add(
            "hidden"
        );

        return;
    }


    stopScanArea.classList.remove(
        "hidden"
    );


    if (
        data.stop_requested ||
        state.stopRequested
    ) {

        stopAnalyzeButton.disabled =
            true;

        stopAnalyzeButton.textContent =
            "Stopping discovery…";

        stopScanHint.textContent =
            "Finishing the current page, then analysis will begin.";

        return;
    }


    stopAnalyzeButton.disabled =
        pdfCount === 0;


    if (pdfCount === 0) {

        stopAnalyzeButton.textContent =
            "Stop & analyze PDFs found so far";

        stopScanHint.textContent =
            "The button becomes available after at least one PDF is found.";

    }

    else {

        stopAnalyzeButton.textContent =
            `Stop & analyze ${pdfCount} PDF${pdfCount === 1 ? "" : "s"}`;

        stopScanHint.textContent =
            "Stops discovery only. PDFs already found will still be analyzed.";
    }
}


function updatePipeline(stage) {

    const order = [
        "discovering",
        "analyzing",
        "grouping",
        "understanding",
        "triaging"
    ];


    let currentIndex =
        order.indexOf(
            stage
        );


    if (
        stage === "complete"
    ) {

        currentIndex =
            order.length;
    }


    document
        .querySelectorAll(
            ".pipeline-step"
        )
        .forEach(
            element => {

                element.classList.remove(
                    "active",
                    "complete"
                );


                const step =
                    element.dataset.stage;


                const index =
                    order.indexOf(
                        step
                    );


                if (
                    index <
                    currentIndex
                ) {

                    element.classList.add(
                        "complete"
                    );
                }


                if (
                    index ===
                    currentIndex
                ) {

                    element.classList.add(
                        "active"
                    );
                }
            }
        );
}


/* ==================================================
   LOAD FINAL RESULTS
================================================== */

async function loadResults() {

    try {

        const [
            resultsResponse,
            familyResponse
        ] =
            await Promise.all([
                fetch(
                    `/api/scan/${state.jobId}/results`
                ),

                fetch(
                    `/api/scan/${state.jobId}/families`
                )
            ]);


        if (!resultsResponse.ok) {

            const data =
                await safeJson(
                    resultsResponse
                );

            throw new Error(
                data.detail ||
                "Could not load scan results."
            );
        }


        const resultsData =
            await resultsResponse.json();


        let familyData = {
            families: []
        };


        if (
            familyResponse.ok
        ) {

            familyData =
                await familyResponse.json();
        }


        state.documents =
            resultsData.documents || [];


        state.families =
            familyData.families || [];


        state.actionCounts =
            resultsData.summary
                ?.action_counts || {};


        state.selectedAction =
            ACTION_ORDER.find(
                action =>
                    (
                        state.actionCounts[
                            action
                        ] || 0
                    ) > 0
            )
            || ACTION_ORDER[0];


        renderResults(
            resultsData.summary || {}
        );


        showView(
            "results"
        );

    }

    catch (error) {

        scanError.textContent =
            error.message;

        scanError.classList.remove(
            "hidden"
        );
    }
}


/* ==================================================
   RESULTS SUMMARY
================================================== */

function renderResults(summary) {

    resultsDomain.textContent =
        state.url;


    if (
        state.stopRequested
    ) {

        resultsMeta.textContent =
            "Partial-site scan · Final Maris recommendations include AI document understanding and retrieved accessibility guidance.";

    }

    else {

        resultsMeta.textContent =
            "Final Maris recommendations · AI document understanding and retrieved accessibility guidance included.";
    }


    totalDocuments.textContent =
        summary.documents_processed ||
        state.documents.length ||
        0;


    const families =
        new Set(
            state.families
                .filter(
                    item =>
                        item.family_id &&
                        item.family_id !==
                            "UNIQUE"
                )
                .map(
                    item =>
                        item.family_id
                )
        );


    familyCount.textContent =
        families.size;


    const forms =
        state.documents.filter(
            document =>
                (
                    document.ai_document_purpose ||
                    document.document_purpose
                ) ===
                "COLLECT_INFORMATION"
        );


    formCount.textContent =
        forms.length;


    renderActionSummary();

    renderActionFilters();

    renderSelectedAction();

    renderFamilies();

    renderAllDocuments(
        state.documents
    );
}


/* ==================================================
   ACTION SUMMARY
================================================== */

function renderActionSummary() {

    actionSummaryGrid.innerHTML =
        "";


    ACTION_ORDER.forEach(
        action => {

            const count =
                state.actionCounts[
                    action
                ] || 0;


            const button =
                document.createElement(
                    "button"
                );


            button.type =
                "button";

            button.className =
                "action-summary-card";


            button.innerHTML = `
                <div class="action-card-count">
                    ${count}
                </div>

                <div class="action-card-bottom">

                    <div class="action-card-name">
                        ${escapeHtml(action)}
                    </div>

                    <div
                        class="action-card-arrow"
                        aria-hidden="true"
                    >
                        →
                    </div>

                </div>
            `;


            button.addEventListener(
                "click",
                () => {

                    state.selectedAction =
                        action;


                    activateTab(
                        "queue"
                    );


                    renderActionFilters();

                    renderSelectedAction();


                    const tabs =
                        document.querySelector(
                            ".tabs"
                        );


                    if (tabs) {

                        tabs.scrollIntoView({
                            behavior:
                                "smooth",
                            block:
                                "start"
                        });
                    }
                }
            );


            actionSummaryGrid.appendChild(
                button
            );
        }
    );
}


/* ==================================================
   ACTION FILTERS
================================================== */

function renderActionFilters() {

    actionFilterList.innerHTML =
        "";


    ACTION_ORDER.forEach(
        action => {

            const count =
                state.actionCounts[
                    action
                ] || 0;


            const button =
                document.createElement(
                    "button"
                );


            button.type =
                "button";

            button.className =
                "action-filter-button";


            if (
                action ===
                state.selectedAction
            ) {

                button.classList.add(
                    "active"
                );
            }


            button.innerHTML = `
                <span>
                    ${escapeHtml(action)}
                </span>

                <span
                    class="action-filter-count"
                >
                    ${count}
                </span>
            `;


            button.addEventListener(
                "click",
                () => {

                    state.selectedAction =
                        action;

                    renderActionFilters();

                    renderSelectedAction();
                }
            );


            actionFilterList.appendChild(
                button
            );
        }
    );
}


/* ==================================================
   SELECTED ACTION
================================================== */

function renderSelectedAction() {

    const action =
        state.selectedAction;


    selectedActionHeading.innerHTML = `
        ${escapeHtml(action)}

        <div
            style="
                margin-top: 6px;
                color: #747891;
                font-size: 13px;
                font-weight: 400;
                line-height: 1.5;
            "
        >
            ${
                escapeHtml(
                    ACTION_DESCRIPTIONS[
                        action
                    ] || ""
                )
            }
        </div>
    `;


    const documents =
        state.documents.filter(
            document =>
                getFinalAction(
                    document
                ) === action
        );


    renderDocumentCards(
        documents,
        actionResults
    );
}


/* ==================================================
   DOCUMENT CARDS
================================================== */

function renderDocumentCards(
    documents,
    container
) {

    container.innerHTML =
        "";


    if (!documents.length) {

        container.innerHTML = `
            <div class="empty-state">
                No documents currently fall into this pathway.
            </div>
        `;

        return;
    }


    documents.forEach(
        document => {

            container.appendChild(
                buildDocumentCard(
                    document
                )
            );
        }
    );
}


function buildDocumentCard(
    document
) {

    const article =
        documentElement(
            "article",
            "result-card"
        );


    const displayName =
        getDocumentDisplayName(
            document
        );


    const priority =
        normalizeLevel(
            document.final_priority ||
            document.rag_priority ||
            document.priority ||
            "Low"
        );


    const confidence =
        normalizeLevel(
            document.final_confidence ||
            document.rag_confidence ||
            document.recommendation_confidence ||
            "Low"
        );


    const purpose =
        document.ai_document_purpose ||
        document.document_purpose ||
        "UNKNOWN";


    const pdfNeed =
        document.ai_pdf_necessity ||
        document.pdf_necessity ||
        "Unknown";


    const documentType =
        document.ai_document_type ||
        document.document_type ||
        "General Document";


    const reason =
        shortenText(
            document.final_reason ||
            document.rag_decision_reason ||
            document.recommendation_reason ||
            "",
            380
        );


    const nextStep =
        getMainNextStep(
            document
        );


    const source =
        cleanSourceHint(
            document.source_application_hint
        );


    const humanReview =
        isHumanReviewRecommended(
            document
        );


    article.innerHTML = `
        <div class="result-top">

            <div>

                <h3 class="result-name">
                    ${
                        escapeHtml(
                            displayName
                        )
                    }
                </h3>

                ${
                    document.pdf_url
                        ? `
                            <div class="result-url">
                                ${
                                    escapeHtml(
                                        document.pdf_url
                                    )
                                }
                            </div>
                        `
                        : ""
                }

                <div class="badge-row">

                    <span
                        class="badge ${priority.toLowerCase()}"
                    >
                        ${escapeHtml(priority)}
                        priority
                    </span>

                    <span class="badge">
                        ${
                            escapeHtml(
                                confidence
                            )
                        }
                        confidence
                    </span>

                    <span class="badge">
                        ${
                            escapeHtml(
                                readablePurpose(
                                    purpose
                                )
                            )
                        }
                    </span>

                    <span class="badge">
                        PDF need:
                        ${
                            escapeHtml(
                                String(
                                    pdfNeed
                                ).toUpperCase()
                            )
                        }
                    </span>

                </div>

            </div>


            ${
                document.pdf_url
                    ? `
                        <a
                            class="open-document"
                            href="${
                                escapeAttribute(
                                    document.pdf_url
                                )
                            }"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            Open PDF ↗
                        </a>
                    `
                    : ""
            }

        </div>


        <div class="result-grid">

            <div class="result-detail">

                <div class="result-detail-label">
                    Why this route
                </div>

                <div class="result-detail-value">
                    ${
                        escapeHtml(
                            reason ||
                            "Maris identified this as the strongest remediation pathway based on document purpose, structure, and retrieved guidance."
                        )
                    }
                </div>

            </div>


            <div class="result-detail">

                <div class="result-detail-label">
                    What to do
                </div>

                <div class="result-detail-value">
                    ${
                        escapeHtml(
                            nextStep
                        )
                    }
                </div>

            </div>

        </div>


        <div class="result-meta-row">

            <span>
                <strong>
                    Document type:
                </strong>

                ${
                    escapeHtml(
                        documentType
                    )
                }
            </span>


            ${
                source
                    ? `
                        <span>
                            <strong>
                                Likely source:
                            </strong>

                            ${
                                escapeHtml(
                                    source
                                )
                            }
                        </span>
                    `
                    : ""
            }


            ${
                humanReview
                    ? `
                        <span
                            class="human-review-pill"
                        >
                            Human review recommended
                        </span>
                    `
                    : ""
            }

        </div>


        ${
            buildDecisionDetails(
                document
            )
        }
    `;


    return article;
}


/* ==================================================
   DECISION DETAILS
================================================== */

function buildDecisionDetails(
    document
) {

    const interaction =
        firstValue(
            document,
            [
                "ai_interaction_type",
                "interaction_type"
            ]
        );


    const alternativeAction =
        firstValue(
            document,
            [
                "rag_alternative_action",
                "alternative_action",
                "ai_alternative_action"
            ]
        );


    const alternativeReason =
        shortenText(
            firstValue(
                document,
                [
                    "rag_alternative_reason",
                    "alternative_reason",
                    "ai_alternative_reason"
                ]
            ),
            280
        );


    const humanReviewReason =
        shortenText(
            firstValue(
                document,
                [
                    "rag_human_review_reason",
                    "human_review_reason",
                    "ai_human_review_reason"
                ]
            ),
            280
        );


    const guidance =
        getGuidanceSourceNames(
            document
        );


    const items = [];


    if (interaction) {

        items.push(`
            <div class="decision-detail-item">

                <div class="result-detail-label">
                    Interaction
                </div>

                <div class="result-detail-value">
                    ${
                        escapeHtml(
                            readableInteraction(
                                interaction
                            )
                        )
                    }
                </div>

            </div>
        `);
    }


    if (guidance) {

        items.push(`
            <div class="decision-detail-item">

                <div class="result-detail-label">
                    Guidance considered
                </div>

                <div class="result-detail-value">
                    ${escapeHtml(guidance)}
                </div>

            </div>
        `);
    }


    if (alternativeAction) {

        items.push(`
            <div class="decision-detail-item">

                <div class="result-detail-label">
                    Alternative pathway
                </div>

                <div class="result-detail-value">

                    ${
                        escapeHtml(
                            alternativeAction
                        )
                    }

                    ${
                        alternativeReason
                            ? `
                                <div class="decision-subtext">
                                    ${
                                        escapeHtml(
                                            alternativeReason
                                        )
                                    }
                                </div>
                            `
                            : ""
                    }

                </div>

            </div>
        `);
    }


    if (humanReviewReason) {

        items.push(`
            <div class="decision-detail-item">

                <div class="result-detail-label">
                    Human review
                </div>

                <div class="result-detail-value">
                    ${
                        escapeHtml(
                            humanReviewReason
                        )
                    }
                </div>

            </div>
        `);
    }


    if (!items.length) {

        return "";
    }


    return `
        <details class="decision-details">

            <summary class="decision-summary">
                View decision details
            </summary>

            <div class="decision-details-grid">
                ${items.join("")}
            </div>

        </details>
    `;
}


/* ==================================================
   SIMILAR DOCUMENT FAMILIES
================================================== */

function renderFamilies() {

    familyResults.innerHTML =
        "";


    const groups =
        new Map();


    state.families.forEach(
        document => {

            const id =
                document.family_id;


            if (
                !id ||
                id === "UNIQUE"
            ) {

                return;
            }


            if (!groups.has(id)) {

                groups.set(
                    id,
                    []
                );
            }


            groups.get(id).push(
                document
            );
        }
    );


    if (!groups.size) {

        familyResults.innerHTML = `
            <div class="empty-state">
                No similar PDF groups were identified.
            </div>
        `;

        return;
    }


    groups.forEach(
        (documents, familyId) => {

            const first =
                documents[0];


            const familyName =
                first.family_name &&
                first.family_name !==
                    "Document Family"
                    ? first.family_name
                    : `PDF group ${familyId}`;


            const article =
                documentElement(
                    "article",
                    "result-card"
                );


            article.innerHTML = `
                <div class="family-card-header">

                    <div>

                        <h3 class="result-name">
                            ${
                                escapeHtml(
                                    familyName
                                )
                            }
                        </h3>

                        <div class="badge-row">

                            <span class="badge">
                                ${documents.length}
                                PDFs
                            </span>

                            ${
                                first.family_confidence
                                    ? `
                                        <span class="badge">
                                            ${
                                                escapeHtml(
                                                    first.family_confidence
                                                )
                                            }
                                            match confidence
                                        </span>
                                    `
                                    : ""
                            }

                            ${
                                first.family_similarity !==
                                undefined
                                    ? `
                                        <span class="badge">
                                            Similarity:
                                            ${
                                                escapeHtml(
                                                    formatSimilarity(
                                                        first.family_similarity
                                                    )
                                                )
                                            }
                                        </span>
                                    `
                                    : ""
                            }

                        </div>

                    </div>

                </div>


                <div class="family-documents">

                    ${
                        documents
                            .map(
                                item => `
                                    <div class="family-document">

                                        <span>
                                            ${
                                                escapeHtml(
                                                    getDocumentDisplayName(
                                                        item
                                                    )
                                                )
                                            }
                                        </span>

                                        ${
                                            item.pdf_url
                                                ? `
                                                    <a
                                                        href="${
                                                            escapeAttribute(
                                                                item.pdf_url
                                                            )
                                                        }"
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                    >
                                                        Open ↗
                                                    </a>
                                                `
                                                : ""
                                        }

                                    </div>
                                `
                            )
                            .join("")
                    }

                </div>
            `;


            familyResults.appendChild(
                article
            );
        }
    );
}


/* ==================================================
   ALL PDF SEARCH
================================================== */

documentSearch.addEventListener(
    "input",
    () => {

        const query =
            documentSearch.value
                .trim()
                .toLowerCase();


        if (!query) {

            renderAllDocuments(
                state.documents
            );

            return;
        }


        const filtered =
            state.documents.filter(
                document => {

                    const values = [
                        getDocumentDisplayName(
                            document
                        ),

                        document.ai_document_type,

                        document.document_type,

                        document.ai_document_purpose,

                        document.document_purpose,

                        getFinalAction(
                            document
                        ),

                        document.source_page,

                        document.pdf_url
                    ];


                    return values
                        .filter(Boolean)
                        .join(" ")
                        .toLowerCase()
                        .includes(query);
                }
            );


        renderAllDocuments(
            filtered
        );
    }
);


function renderAllDocuments(
    documents
) {

    renderDocumentCards(
        documents,
        allDocuments
    );
}


/* ==================================================
   TABS
================================================== */

document
    .querySelectorAll(
        ".tab-button"
    )
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    activateTab(
                        button.dataset.tab
                    );
                }
            );
        }
    );


function activateTab(
    tabName
) {

    document
        .querySelectorAll(
            ".tab-button"
        )
        .forEach(
            button => {

                button.classList.toggle(
                    "active",
                    button.dataset.tab ===
                        tabName
                );
            }
        );


    document
        .querySelectorAll(
            ".tab-panel"
        )
        .forEach(
            panel => {

                panel.classList.add(
                    "hidden"
                );
            }
        );


    const panels = {
        queue:
            document.getElementById(
                "queuePanel"
            ),

        families:
            document.getElementById(
                "familiesPanel"
            ),

        all:
            document.getElementById(
                "allPanel"
            )
    };


    if (
        panels[
            tabName
        ]
    ) {

        panels[
            tabName
        ].classList.remove(
            "hidden"
        );
    }
}


/* ==================================================
   NEW SCAN
================================================== */

newScanButton.addEventListener(
    "click",
    resetApp
);


newScanHeaderButton.addEventListener(
    "click",
    resetApp
);


/* ==================================================
   DOCUMENT DISPLAY NAME
================================================== */

function getDocumentDisplayName(
    document
) {

    const names = [
        document.filename,
        document.file_name,
        document.name,
        document.title
    ];


    for (
        const value
        of names
    ) {

        if (
            value &&
            String(
                value
            ).trim() &&
            String(
                value
            ).trim()
                .toLowerCase() !==
                "untitled pdf"
        ) {

            return String(
                value
            ).trim();
        }
    }


    const url =
        document.pdf_url ||
        "";


    if (url) {

        try {

            const parsed =
                new URL(
                    url
                );


            const parts =
                parsed.pathname
                    .split("/")
                    .filter(Boolean);


            if (
                parts.length
            ) {

                const filename =
                    decodeURIComponent(
                        parts[
                            parts.length - 1
                        ]
                    );


                if (
                    filename
                ) {

                    return filename;
                }
            }

        }

        catch {

            const parts =
                url
                    .split("?")[0]
                    .split("/")
                    .filter(Boolean);


            if (
                parts.length
            ) {

                return decodeURIComponent(
                    parts[
                        parts.length - 1
                    ]
                );
            }
        }
    }


    return (
        document.ai_document_type ||
        document.document_type ||
        "PDF document"
    );
}


/* ==================================================
   FINAL ACTION
================================================== */

function getFinalAction(
    document
) {

    return (
        document.final_recommended_action ||
        document.rag_action ||
        document.recommended_action ||
        "Keep / Review"
    );
}


/* ==================================================
   NEXT STEP
================================================== */

function getMainNextStep(
    document
) {

    const action =
        getFinalAction(
            document
        );


    const source =
        cleanSourceHint(
            document.source_application_hint
        );


    const sourceText =
        source
            ? ` in ${source}`
            : " in the original source file";


    const steps = {

        "Convert to HTML":
            "Publish the essential information as accessible HTML. If the PDF must remain available, keep it as a supplemental accessible download.",

        "Convert to Web Form":
            "Rebuild the workflow as an accessible web form. Preserve required labels, instructions, validation, signatures, eligibility steps, and staff workflow.",

        "Fix Source & Re-export":
            `Correct headings, lists, tables, reading order, alternative text, and other accessibility issues${sourceText}, then export and test a new accessible PDF.`,

        "Remediate PDF":
            "Repair the existing PDF directly and test the remediated document with appropriate accessibility tools before republishing.",

        "Specialist Review":
            "Have an accessibility specialist review the document's visual, interactive, spatial, or workflow requirements before choosing the final remediation pathway.",

        "Keep / Review":
            "Confirm that the PDF still has a legitimate archival, print, download, record, or fixed-layout purpose, then verify that the retained PDF is accessible.",

        "External Owner Review":
            "Confirm who owns the document and request an accessible version or remediation plan from the external publisher."
    };


    return (
        steps[
            action
        ] ||
        "Review the document and confirm the appropriate remediation pathway."
    );
}


/* ==================================================
   HUMAN REVIEW
================================================== */

function isHumanReviewRecommended(
    document
) {

    const value =
        firstValue(
            document,
            [
                "rag_human_review_required",
                "human_review_required",
                "ai_human_review_required"
            ]
        );


    if (
        typeof value ===
        "boolean"
    ) {

        return value;
    }


    const normalized =
        String(
            value
        )
        .trim()
        .toLowerCase();


    return (
        normalized === "true" ||
        normalized === "yes" ||
        normalized === "1"
    );
}


/* ==================================================
   RAG GUIDANCE SOURCES
================================================== */

function getGuidanceSourceNames(
    document
) {

    const candidates = [
        document.retrieved_guidance_sources,
        document.rag_sources,
        document.rag_guidance_sources,
        document.guidance_sources
    ];


    for (
        const raw
        of candidates
    ) {

        const result =
            parseGuidanceSources(
                raw
            );


        if (result) {

            return result;
        }
    }


    return "";
}


function parseGuidanceSources(
    raw
) {

    if (!raw) {
        return "";
    }


    if (
        Array.isArray(
            raw
        )
    ) {

        const names =
            raw
                .map(
                    item => {

                        if (
                            typeof item ===
                            "string"
                        ) {

                            return item;
                        }


                        return (
                            item.source ||
                            item.source_name ||
                            item.title ||
                            ""
                        );
                    }
                )
                .filter(Boolean);


        return unique(
            names
        ).join(", ");
    }


    if (
        typeof raw ===
        "object"
    ) {

        const value =
            raw.source ||
            raw.source_name ||
            raw.title;


        return value
            ? String(value)
            : "";
    }


    const text =
        String(
            raw
        ).trim();


    if (!text) {
        return "";
    }


    try {

        const parsed =
            JSON.parse(
                text
            );


        return parseGuidanceSources(
            parsed
        );

    }

    catch {

        const known = [];


        if (
            /w3c/i.test(
                text
            )
        ) {

            known.push(
                "W3C"
            );
        }


        if (
            /section.?508/i.test(
                text
            )
        ) {

            known.push(
                "Section508.gov"
            );
        }


        if (
            /digital\.?gov/i.test(
                text
            )
        ) {

            known.push(
                "Digital.gov"
            );
        }


        if (
            /pdf\/ua/i.test(
                text
            )
        ) {

            known.push(
                "PDF/UA"
            );
        }


        if (
            known.length
        ) {

            return unique(
                known
            ).join(", ");
        }


        return shortenText(
            text,
            180
        );
    }
}


/* ==================================================
   PURPOSE LABELS
================================================== */

function readablePurpose(
    purpose
) {

    const values = {

        INFORM:
            "Informational",

        PROMOTE_EVENT:
            "Event information",

        COLLECT_INFORMATION:
            "Data collection",

        PROVIDE_DIRECTIONS:
            "Directions",

        REFERENCE:
            "Reference",

        OFFICIAL_RECORD:
            "Official record",

        FORMAL_PUBLICATION:
            "Formal publication",

        INSTRUCT:
            "Instructions",

        UNKNOWN:
            "Unknown purpose"
    };


    return (
        values[
            String(
                purpose || ""
            ).toUpperCase()
        ] ||
        titleCaseFromCode(
            purpose
        ) ||
        "Unknown purpose"
    );
}


/* ==================================================
   INTERACTION LABELS
================================================== */

function readableInteraction(
    interaction
) {

    const value =
        String(
            interaction || ""
        ).toUpperCase();


    const values = {

        READ_ONLY:
            "Read only",

        DATA_ENTRY:
            "Data entry",

        FORM:
            "Form interaction",

        SIGNATURE:
            "Signature workflow",

        SIGNATURE_WORKFLOW:
            "Signature workflow",

        STAFF_WORKFLOW:
            "Staff workflow",

        SPATIAL_NAVIGATION:
            "Spatial navigation",

        MAP:
            "Spatial navigation",

        REFERENCE:
            "Read / reference",

        MIXED:
            "Mixed interaction",

        UNKNOWN:
            "Unknown"
    };


    return (
        values[
            value
        ] ||
        titleCaseFromCode(
            interaction
        )
    );
}


/* ==================================================
   TEXT HELPERS
================================================== */

function shortenText(
    value,
    maxLength = 350
) {

    const text =
        String(
            value || ""
        )
        .replace(/\s+/g, " ")
        .trim();


    if (
        text.length <=
        maxLength
    ) {

        return text;
    }


    const shortened =
        text.slice(
            0,
            maxLength
        );


    const sentenceEnd =
        Math.max(
            shortened.lastIndexOf("."),
            shortened.lastIndexOf("!"),
            shortened.lastIndexOf("?")
        );


    if (
        sentenceEnd >
        maxLength * 0.55
    ) {

        return shortened
            .slice(
                0,
                sentenceEnd + 1
            )
            .trim();
    }


    const wordEnd =
        shortened.lastIndexOf(
            " "
        );


    if (
        wordEnd > 0
    ) {

        return (
            shortened
                .slice(
                    0,
                    wordEnd
                )
                .trim()
            + "…"
        );
    }


    return (
        shortened.trim()
        + "…"
    );
}


function firstValue(
    object,
    keys
) {

    for (
        const key
        of keys
    ) {

        const value =
            object[
                key
            ];


        if (
            value !== undefined &&
            value !== null &&
            String(
                value
            ).trim() !== ""
        ) {

            return value;
        }
    }


    return "";
}


function cleanSourceHint(
    value
) {

    const text =
        String(
            value || ""
        ).trim();


    if (
        !text ||
        text.toLowerCase() ===
            "unknown" ||
        text.toLowerCase() ===
            "nan"
    ) {

        return "";
    }


    return text;
}


function normalizeLevel(
    value
) {

    const text =
        String(
            value || ""
        )
        .trim()
        .toLowerCase();


    if (
        text === "high"
    ) {

        return "High";
    }


    if (
        text === "medium"
    ) {

        return "Medium";
    }


    if (
        text === "low"
    ) {

        return "Low";
    }


    return (
        titleCaseFromCode(
            value
        ) ||
        "Low"
    );
}


function titleCaseFromCode(
    value
) {

    const text =
        String(
            value || ""
        )
        .trim();


    if (!text) {
        return "";
    }


    return text
        .replace(
            /[_-]+/g,
            " "
        )
        .toLowerCase()
        .replace(
            /\b\w/g,
            character =>
                character.toUpperCase()
        );
}


function unique(
    values
) {

    return [
        ...new Set(
            values
        )
    ];
}


/* ==================================================
   FAMILY SIMILARITY
================================================== */

function formatSimilarity(
    value
) {

    const number =
        Number(
            value
        );


    if (
        Number.isNaN(
            number
        )
    ) {

        return "Unknown";
    }


    if (
        number <= 1
    ) {

        return `${
            Math.round(
                number * 100
            )
        }%`;
    }


    return `${
        Math.round(
            number
        )
    }%`;
}


/* ==================================================
   URL HELPERS
================================================== */

function normalizeDisplayUrl(
    url
) {

    try {

        const normalized =
            /^https?:\/\//i
                .test(
                    url
                )
                ? url
                : `https://${url}`;


        return new URL(
            normalized
        ).hostname;

    }

    catch {

        return url;
    }
}


/* ==================================================
   DOM HELPERS
================================================== */

function documentElement(
    tag,
    className
) {

    const element =
        document.createElement(
            tag
        );


    element.className =
        className;


    return element;
}


/* ==================================================
   HTML ESCAPING
================================================== */

function escapeHtml(
    value
) {

    return String(
        value ?? ""
    )
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
}


function escapeAttribute(
    value
) {

    return escapeHtml(
        value
    );
}


/* ==================================================
   FETCH HELPERS
================================================== */

async function safeJson(
    response
) {

    try {

        return await response.json();

    }

    catch {

        return {};
    }
}


/* ==================================================
   INITIAL VIEW
================================================== */

showView(
    "landing"
);