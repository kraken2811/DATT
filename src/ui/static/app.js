/**
 * DATT AI Vision Monitor & Camera Manager - Frontend Client
 * Phase 4.6: Initial Camera Selection, Public CCTV, Direct HLS & Multi-Source Routing
 *
 * UI States:
 * - SELECT_CAMERA : Initial selection screen (Public CCTV, Direct HLS, YouTube Live, Local)
 * - CONNECTING    : Connecting overlay, verifying first frame
 * - MONITORING    : Active monitoring dashboard
 * - ERROR         : Connection timeout or failure screen with retry
 */

(function () {
    "use strict";

    // Application Configuration
    const CONFIG = {
        telemetryIntervalMs: 1000,
        eventsIntervalMs: 10000,
        videoReconnectDelayMs: 3000,
        connectionTimeoutMs: 16000,
        sourceStatusPollMs: 500,
        defaultBackendUrl: "http://localhost:8000"
    };

    // UI States
    const UI_STATE = {
        SELECT_CAMERA: "SELECT_CAMERA",
        CONNECTING: "CONNECTING",
        MONITORING: "MONITORING",
        ERROR: "ERROR",
        WATCHLIST: "WATCHLIST",
        CAMERA_MANAGEMENT: "CAMERA_MANAGEMENT",
        EVENT_CENTER: "EVENT_CENTER"
    };

    // Client State
    const state = {
        uiState: UI_STATE.SELECT_CAMERA,
        backendUrl: CONFIG.defaultBackendUrl,
        activeCameraId: "",
        activeCameraName: "",
        activeProvider: "",
        activeSourceType: "",
        connectingSourceData: null,
        isSwitchingCamera: false,
        telemetryTimer: null,
        eventsTimer: null,
        videoReconnectTimer: null,
        connectionTimer: null,
        lastEventsJson: "",
        consecutiveErrors: 0,
        cctvCameras: [],
        cctvProvider: "seattle",
        previewingCamera: null,
        isPreviewLive: false
    };

    // DOM Elements Cache
    const DOM = {
        // Screens
        selectionScreen: document.getElementById("selectionScreen"),
        connectingScreen: document.getElementById("connectingScreen"),
        errorScreen: document.getElementById("errorScreen"),
        monitoringScreen: document.getElementById("monitoringScreen"),
        watchlistScreen: document.getElementById("watchlistScreen"),

        // Watchlist Navigation Badges
        selectionWatchlistBadge: document.getElementById("selectionWatchlistBadge"),
        navWatchlistBadgeDash: document.getElementById("navWatchlistBadgeDash"),
        navWatchlistBadgeWl: document.getElementById("navWatchlistBadgeWl"),

        // Watchlist Center Elements
        btnRefreshWatchlist: document.getElementById("btnRefreshWatchlist"),
        tabBtnWatchlistFace: document.getElementById("tabBtnWatchlistFace"),
        tabBtnWatchlistVehicle: document.getElementById("tabBtnWatchlistVehicle"),
        faceHeroTotalCount: document.getElementById("faceHeroTotalCount"),
        vehicleHeroTotalCount: document.getElementById("vehicleHeroTotalCount"),
        watchlistBanner: document.getElementById("watchlistBanner"),

        // Face Watchlist Pane Elements
        paneFaceWatchlist: document.getElementById("paneFaceWatchlist"),
        faceStatTotal: document.getElementById("faceStatTotal"),
        faceStatActive: document.getElementById("faceStatActive"),
        faceStatDetectedToday: document.getElementById("faceStatDetectedToday"),
        faceSearchInput: document.getElementById("faceSearchInput"),
        faceStatusFilter: document.getElementById("faceStatusFilter"),
        faceSortFilter: document.getElementById("faceSortFilter"),
        btnOpenAddFaceModal: document.getElementById("btnOpenAddFaceModal"),
        faceTableSkeleton: document.getElementById("faceTableSkeleton"),
        faceTableError: document.getElementById("faceTableError"),
        faceTableErrorMsg: document.getElementById("faceTableErrorMsg"),
        btnRetryLoadFaces: document.getElementById("btnRetryLoadFaces"),
        faceTableEmpty: document.getElementById("faceTableEmpty"),
        btnEmptyAddFace: document.getElementById("btnEmptyAddFace"),
        faceTableWrapper: document.getElementById("faceTableWrapper"),
        faceTableBody: document.getElementById("faceTableBody"),

        // Vehicle Watchlist Pane Elements
        paneVehicleWatchlist: document.getElementById("paneVehicleWatchlist"),
        vehicleStatTotal: document.getElementById("vehicleStatTotal"),
        vehicleStatActive: document.getElementById("vehicleStatActive"),
        vehicleStatDetectedToday: document.getElementById("vehicleStatDetectedToday"),
        vehicleSearchInput: document.getElementById("vehicleSearchInput"),
        vehicleTypeFilter: document.getElementById("vehicleTypeFilter"),
        vehicleStatusFilter: document.getElementById("vehicleStatusFilter"),
        btnOpenAddVehicleModal: document.getElementById("btnOpenAddVehicleModal"),
        vehicleTableSkeleton: document.getElementById("vehicleTableSkeleton"),
        vehicleTableError: document.getElementById("vehicleTableError"),
        vehicleTableErrorMsg: document.getElementById("vehicleTableErrorMsg"),
        btnRetryLoadVehicles: document.getElementById("btnRetryLoadVehicles"),
        vehicleTableEmpty: document.getElementById("vehicleTableEmpty"),
        btnEmptyAddVehicle: document.getElementById("btnEmptyAddVehicle"),
        vehicleTableWrapper: document.getElementById("vehicleTableWrapper"),
        vehicleTableBody: document.getElementById("vehicleTableBody"),

        // Drawers & Modals
        drawerBackdrop: document.getElementById("drawerBackdrop"),
        drawerFaceDetail: document.getElementById("drawerFaceDetail"),
        btnCloseFaceDrawer: document.getElementById("btnCloseFaceDrawer"),
        faceDrawerName: document.getElementById("faceDrawerName"),
        faceDrawerId: document.getElementById("faceDrawerId"),
        faceDrawerStatus: document.getElementById("faceDrawerStatus"),
        faceDrawerAvatar: document.getElementById("faceDrawerAvatar"),
        faceDrawerCreatedAt: document.getElementById("faceDrawerCreatedAt"),
        faceDrawerThreshold: document.getElementById("faceDrawerThreshold"),
        faceDrawerColor: document.getElementById("faceDrawerColor"),
        faceDrawerDetectionCount: document.getElementById("faceDrawerDetectionCount"),
        faceDrawerLastSeen: document.getElementById("faceDrawerLastSeen"),
        faceDrawerHistoryBadge: document.getElementById("faceDrawerHistoryBadge"),
        faceDrawerHistoryLoading: document.getElementById("faceDrawerHistoryLoading"),
        faceDrawerHistoryEmpty: document.getElementById("faceDrawerHistoryEmpty"),
        faceDrawerHistoryList: document.getElementById("faceDrawerHistoryList"),
        btnToggleFaceStatus: document.getElementById("btnToggleFaceStatus"),
        faceToggleBtnText: document.getElementById("faceToggleBtnText"),
        btnDeleteFaceTarget: document.getElementById("btnDeleteFaceTarget"),

        drawerVehicleDetail: document.getElementById("drawerVehicleDetail"),
        btnCloseVehicleDrawer: document.getElementById("btnCloseVehicleDrawer"),
        vehicleDrawerPlateBadge: document.getElementById("vehicleDrawerPlateBadge"),
        vehicleDrawerStatus: document.getElementById("vehicleDrawerStatus"),
        vehicleDrawerType: document.getElementById("vehicleDrawerType"),
        vehicleDrawerName: document.getElementById("vehicleDrawerName"),
        vehicleDrawerOwner: document.getElementById("vehicleDrawerOwner"),
        vehicleDrawerNotes: document.getElementById("vehicleDrawerNotes"),
        vehicleDrawerCreatedAt: document.getElementById("vehicleDrawerCreatedAt"),
        vehicleDrawerDetectionCount: document.getElementById("vehicleDrawerDetectionCount"),
        vehicleDrawerLastSeen: document.getElementById("vehicleDrawerLastSeen"),
        vehicleDrawerHistoryBadge: document.getElementById("vehicleDrawerHistoryBadge"),
        vehicleDrawerHistoryLoading: document.getElementById("vehicleDrawerHistoryLoading"),
        vehicleDrawerHistoryEmpty: document.getElementById("vehicleDrawerHistoryEmpty"),
        vehicleDrawerHistoryList: document.getElementById("vehicleDrawerHistoryList"),
        btnToggleVehicleStatus: document.getElementById("btnToggleVehicleStatus"),
        vehicleToggleBtnText: document.getElementById("vehicleToggleBtnText"),
        btnDeleteVehicleItem: document.getElementById("btnDeleteVehicleItem"),

        modalAddFaceWatchlist: document.getElementById("modalAddFaceWatchlist"),
        btnCloseAddFaceWatchlist: document.getElementById("btnCloseAddFaceWatchlist"),
        btnCancelAddFaceWatchlist: document.getElementById("btnCancelAddFaceWatchlist"),
        faceDropzoneNew: document.getElementById("faceDropzoneNew"),
        faceFileInputNew: document.getElementById("faceFileInputNew"),
        btnBrowseFaceNew: document.getElementById("btnBrowseFaceNew"),
        facePreviewCardNew: document.getElementById("facePreviewCardNew"),
        facePreviewImgNew: document.getElementById("facePreviewImgNew"),
        facePreviewNameNew: document.getElementById("facePreviewNameNew"),
        facePreviewSizeNew: document.getElementById("facePreviewSizeNew"),
        btnRemoveFacePreviewNew: document.getElementById("btnRemoveFacePreviewNew"),
        inputNewFaceName: document.getElementById("inputNewFaceName"),
        selectNewFaceColor: document.getElementById("selectNewFaceColor"),
        inputNewFaceThreshold: document.getElementById("inputNewFaceThreshold"),
        inputNewFaceNotes: document.getElementById("inputNewFaceNotes"),
        addFaceFeedbackNew: document.getElementById("addFaceFeedbackNew"),
        btnSubmitAddFaceWatchlist: document.getElementById("btnSubmitAddFaceWatchlist"),

        modalAddVehicleWatchlist: document.getElementById("modalAddVehicleWatchlist"),
        btnCloseAddVehicleWatchlist: document.getElementById("btnCloseAddVehicleWatchlist"),
        btnCancelAddVehicleWatchlist: document.getElementById("btnCancelAddVehicleWatchlist"),
        inputNewVehiclePlate: document.getElementById("inputNewVehiclePlate"),
        plateNormalizedBadge: document.getElementById("plateNormalizedBadge"),
        selectNewVehicleType: document.getElementById("selectNewVehicleType"),
        selectNewVehicleStatus: document.getElementById("selectNewVehicleStatus"),
        inputNewVehicleName: document.getElementById("inputNewVehicleName"),
        inputNewVehicleOwner: document.getElementById("inputNewVehicleOwner"),
        inputNewVehicleNotes: document.getElementById("inputNewVehicleNotes"),
        addVehicleFeedback: document.getElementById("addVehicleFeedback"),
        btnSubmitAddVehicleWatchlist: document.getElementById("btnSubmitAddVehicleWatchlist"),

        modalConfirmDelete: document.getElementById("modalConfirmDelete"),
        btnCloseConfirmDelete: document.getElementById("btnCloseConfirmDelete"),
        btnCancelConfirmDelete: document.getElementById("btnCancelConfirmDelete"),
        btnExecuteConfirmDelete: document.getElementById("btnExecuteConfirmDelete"),
        confirmDeleteTargetName: document.getElementById("confirmDeleteTargetName"),
        confirmDeleteFeedback: document.getElementById("confirmDeleteFeedback"),

        // Camera Management Elements
        cameraManagementScreen: document.getElementById("cameraManagementScreen"),
        camTotalVal: document.getElementById("camTotalVal"),
        camOnlineVal: document.getElementById("camOnlineVal"),
        camOfflineVal: document.getElementById("camOfflineVal"),
        camDisabledVal: document.getElementById("camDisabledVal"),
        navCameraCountBadge: document.getElementById("navCameraCountBadge"),
        btnOpenAddCameraModal: document.getElementById("btnOpenAddCameraModal"),
        btnToolbarAddCamera: document.getElementById("btnToolbarAddCamera"),
        btnSwitchToSelection: document.getElementById("btnSwitchToSelection"),
        btnRefreshCameras: document.getElementById("btnRefreshCameras"),
        cameraSearchInput: document.getElementById("cameraSearchInput"),
        cameraStatusFilter: document.getElementById("cameraStatusFilter"),
        cameraTypeFilter: document.getElementById("cameraTypeFilter"),
        cameraZoneFilter: document.getElementById("cameraZoneFilter"),
        cameraTableSkeleton: document.getElementById("cameraTableSkeleton"),
        cameraTableEmpty: document.getElementById("cameraTableEmpty"),
        cameraFilterEmpty: document.getElementById("cameraFilterEmpty"),
        btnResetCameraFilters: document.getElementById("btnResetCameraFilters"),
        btnEmptyAddCamera: document.getElementById("btnEmptyAddCamera"),
        cameraTableError: document.getElementById("cameraTableError"),
        cameraErrorMsg: document.getElementById("cameraErrorMsg"),
        btnRetryLoadCameras: document.getElementById("btnRetryLoadCameras"),
        cameraTableWrapper: document.getElementById("cameraTableWrapper"),
        cameraTableBody: document.getElementById("cameraTableBody"),
        cameraFeedbackBanner: document.getElementById("cameraFeedbackBanner"),

        // Drawer Camera Detail
        drawerCameraDetail: document.getElementById("drawerCameraDetail"),
        btnCloseCameraDrawer: document.getElementById("btnCloseCameraDrawer"),
        camDrawerTitle: document.getElementById("camDrawerTitle"),
        camDrawerId: document.getElementById("camDrawerId"),
        camDrawerStatus: document.getElementById("camDrawerStatus"),
        camDrawerPreviewType: document.getElementById("camDrawerPreviewType"),
        camDrawerPreviewUrl: document.getElementById("camDrawerPreviewUrl"),
        camDrawerGraphicLabel: document.getElementById("camDrawerGraphicLabel"),
        camDrawerPingBadge: document.getElementById("camDrawerPingBadge"),
        camDrawerStreamHealth: document.getElementById("camDrawerStreamHealth"),
        camDrawerUrl: document.getElementById("camDrawerUrl"),
        camDrawerZone: document.getElementById("camDrawerZone"),
        camDrawerType: document.getElementById("camDrawerType"),
        camDrawerCreated: document.getElementById("camDrawerCreated"),
        camDrawerLastActive: document.getElementById("camDrawerLastActive"),
        camDrawerDesc: document.getElementById("camDrawerDesc"),
        btnLaunchMonitoringFromDrawer: document.getElementById("btnLaunchMonitoringFromDrawer"),
        btnEditCamFromDrawer: document.getElementById("btnEditCamFromDrawer"),
        btnToggleStatusFromDrawer: document.getElementById("btnToggleStatusFromDrawer"),
        camDrawerToggleText: document.getElementById("camDrawerToggleText"),
        btnDeleteCamFromDrawer: document.getElementById("btnDeleteCamFromDrawer"),

        // Modal Add Camera
        modalAddCamera: document.getElementById("modalAddCamera"),
        btnCloseAddCameraModal: document.getElementById("btnCloseAddCameraModal"),
        btnCancelAddCamera: document.getElementById("btnCancelAddCamera"),
        btnSubmitAddCamera: document.getElementById("btnSubmitAddCamera"),
        inputAddCamName: document.getElementById("inputAddCamName"),
        inputAddCamUrl: document.getElementById("inputAddCamUrl"),
        selectAddCamType: document.getElementById("selectAddCamType"),
        selectAddCamStatus: document.getElementById("selectAddCamStatus"),
        inputAddCamZone: document.getElementById("inputAddCamZone"),
        inputAddCamDesc: document.getElementById("inputAddCamDesc"),
        btnTestConnAdd: document.getElementById("btnTestConnAdd"),
        testConnResultAdd: document.getElementById("testConnResultAdd"),
        addCamFormFeedback: document.getElementById("addCamFormFeedback"),

        // Modal Edit Camera
        modalEditCamera: document.getElementById("modalEditCamera"),
        btnCloseEditCameraModal: document.getElementById("btnCloseEditCameraModal"),
        btnCancelEditCamera: document.getElementById("btnCancelEditCamera"),
        btnSubmitEditCamera: document.getElementById("btnSubmitEditCamera"),
        editCamIdBadge: document.getElementById("editCamIdBadge"),
        inputEditCamId: document.getElementById("inputEditCamId"),
        inputEditCamName: document.getElementById("inputEditCamName"),
        inputEditCamUrl: document.getElementById("inputEditCamUrl"),
        selectEditCamType: document.getElementById("selectEditCamType"),
        selectEditCamStatus: document.getElementById("selectEditCamStatus"),
        inputEditCamZone: document.getElementById("inputEditCamZone"),
        inputEditCamDesc: document.getElementById("inputEditCamDesc"),
        btnTestConnEdit: document.getElementById("btnTestConnEdit"),
        testConnResultEdit: document.getElementById("testConnResultEdit"),
        editCamFormFeedback: document.getElementById("editCamFormFeedback"),

        // Modal Delete Camera
        modalDeleteCamera: document.getElementById("modalDeleteCamera"),
        btnCloseDeleteCameraModal: document.getElementById("btnCloseDeleteCameraModal"),
        btnCancelDeleteCamera: document.getElementById("btnCancelDeleteCamera"),
        btnConfirmDeleteCamera: document.getElementById("btnConfirmDeleteCamera"),
        deleteCamTargetName: document.getElementById("deleteCamTargetName"),
        deleteCamTargetId: document.getElementById("deleteCamTargetId"),
        deleteCamFeedback: document.getElementById("deleteCamFeedback"),

        // Vehicle Watchlist Edit Modal & Drawer Edit Button
        btnEditVehicleItem: document.getElementById("btnEditVehicleItem"),
        modalEditVehicleWatchlist: document.getElementById("modalEditVehicleWatchlist"),
        btnCloseEditVehicleWatchlist: document.getElementById("btnCloseEditVehicleWatchlist"),
        btnCancelEditVehicleWatchlist: document.getElementById("btnCancelEditVehicleWatchlist"),
        btnSubmitEditVehicleWatchlist: document.getElementById("btnSubmitEditVehicleWatchlist"),
        inputEditVehicleId: document.getElementById("inputEditVehicleId"),
        badgeEditVehiclePlate: document.getElementById("badgeEditVehiclePlate"),
        selectEditVehicleType: document.getElementById("selectEditVehicleType"),
        selectEditVehicleStatus: document.getElementById("selectEditVehicleStatus"),
        inputEditVehicleName: document.getElementById("inputEditVehicleName"),
        inputEditVehicleOwner: document.getElementById("inputEditVehicleOwner"),
        inputEditVehicleNotes: document.getElementById("inputEditVehicleNotes"),
        editVehicleFeedback: document.getElementById("editVehicleFeedback"),

        // Event Center Screen & Elements
        eventCenterScreen: document.getElementById("eventCenterScreen"),
        evNavEvents: document.getElementById("evNavEvents"),
        navEventCountBadge: document.getElementById("navEventCountBadge"),
        navCameraCountBadgeEv: document.getElementById("navCameraCountBadgeEv"),
        navWatchlistBadgeEv: document.getElementById("navWatchlistBadgeEv"),
        btnRefreshEvents: document.getElementById("btnRefreshEvents"),

        // Event Center Summary Counters
        evTotalCount: document.getElementById("evTotalCount"),
        evFaceCount: document.getElementById("evFaceCount"),
        evPlateVehicleCount: document.getElementById("evPlateVehicleCount"),
        evMatchCount: document.getElementById("evMatchCount"),

        // Event Center Tabs & Filters
        eventTabsBar: document.getElementById("eventTabsBar"),
        eventFilterCamera: document.getElementById("eventFilterCamera"),
        eventFilterType: document.getElementById("eventFilterType"),
        eventFilterTarget: document.getElementById("eventFilterTarget"),
        eventFilterPlate: document.getElementById("eventFilterPlate"),
        eventFilterMatch: document.getElementById("eventFilterMatch"),
        eventFilterNotification: document.getElementById("eventFilterNotification"),
        eventFilterFromTime: document.getElementById("eventFilterFromTime"),
        eventFilterToTime: document.getElementById("eventFilterToTime"),
        btnApplyEventFilters: document.getElementById("btnApplyEventFilters"),
        btnClearEventFilters: document.getElementById("btnClearEventFilters"),
        eventSortSelect: document.getElementById("eventSortSelect"),

        // Event Center Table & State Placeholders
        eventTableSkeleton: document.getElementById("eventTableSkeleton"),
        eventTableError: document.getElementById("eventTableError"),
        eventErrorMsg: document.getElementById("eventErrorMsg"),
        btnRetryLoadEvents: document.getElementById("btnRetryLoadEvents"),
        eventTableEmpty: document.getElementById("eventTableEmpty"),
        eventFilterEmpty: document.getElementById("eventFilterEmpty"),
        btnResetEventFilterEmpty: document.getElementById("btnResetEventFilterEmpty"),
        eventTableWrapper: document.getElementById("eventTableWrapper"),
        eventTable: document.getElementById("eventTable"),
        eventTableBody: document.getElementById("eventTableBody"),

        // Event Center Pagination
        eventPaginationFooter: document.getElementById("eventPaginationFooter"),
        eventPaginationInfo: document.getElementById("eventPaginationInfo"),
        btnEventPrevPage: document.getElementById("btnEventPrevPage"),
        btnEventNextPage: document.getElementById("btnEventNextPage"),
        eventCurrentPageBadge: document.getElementById("eventCurrentPageBadge"),

        // Event Center Detail Drawer
        drawerEventDetail: document.getElementById("drawerEventDetail"),
        btnCloseEventDrawer: document.getElementById("btnCloseEventDrawer"),
        btnCloseEventDrawerFooter: document.getElementById("btnCloseEventDrawerFooter"),
        evDrawerBadgeType: document.getElementById("evDrawerBadgeType"),
        evDrawerTitle: document.getElementById("evDrawerTitle"),
        evDrawerIdSub: document.getElementById("evDrawerIdSub"),
        evDrawerMatchPill: document.getElementById("evDrawerMatchPill"),
        evDrawerEvidenceStatusBadge: document.getElementById("evDrawerEvidenceStatusBadge"),
        evDrawerEvidenceBox: document.getElementById("evDrawerEvidenceBox"),
        evDrawerEvidenceImg: document.getElementById("evDrawerEvidenceImg"),
        evDrawerEvidenceUnavailable: document.getElementById("evDrawerEvidenceUnavailable"),
        evDrawerEvidenceLoading: document.getElementById("evDrawerEvidenceLoading"),
        evDrawerId: document.getElementById("evDrawerId"),
        evDrawerType: document.getElementById("evDrawerType"),
        evDrawerTimestamp: document.getElementById("evDrawerTimestamp"),
        evDrawerCamera: document.getElementById("evDrawerCamera"),
        evDrawerObjectType: document.getElementById("evDrawerObjectType"),
        evDrawerTarget: document.getElementById("evDrawerTarget"),
        evDrawerPlate: document.getElementById("evDrawerPlate"),
        evDrawerSimilarity: document.getElementById("evDrawerSimilarity"),
        evDrawerConfidence: document.getElementById("evDrawerConfidence"),
        evDrawerMatch: document.getElementById("evDrawerMatch"),
        evDrawerNotification: document.getElementById("evDrawerNotification"),
        evDrawerExtendedSection: document.getElementById("evDrawerExtendedSection"),
        evDrawerExtendedList: document.getElementById("evDrawerExtendedList"),
        evDrawerExtendedText: document.getElementById("evDrawerExtendedText"),

        // Connecting & Error UI
        connectingTargetName: document.getElementById("connectingTargetName"),
        badgeStepReader: document.getElementById("badgeStepReader"),
        badgeStepFrame: document.getElementById("badgeStepFrame"),
        badgeStepAi: document.getElementById("badgeStepAi"),
        errorMessageText: document.getElementById("errorMessageText"),
        errorDebugBox: document.getElementById("errorDebugBox"),
        btnRetryConnection: document.getElementById("btnRetryConnection"),
        btnBackToSelection: document.getElementById("btnBackToSelection"),

        // Source Header on Dashboard
        dashHeaderCamName: document.getElementById("dashHeaderCamName"),
        dashHeaderProvider: document.getElementById("dashHeaderProvider"),
        dashHeaderStatus: document.getElementById("dashHeaderStatus"),
        btnSwitchCameraFromDash: document.getElementById("btnSwitchCameraFromDash"),

        // Public CCTV Catalog Elements
        cctvSearchInput: document.getElementById("cctvSearchInput"),
        cctvCountBadge: document.getElementById("cctvCountBadge"),
        refreshCatalogBtn: document.getElementById("refreshCatalogBtn"),
        cctvCardsGrid: document.getElementById("cctvCardsGrid"),

        // Direct HLS Tab Elements
        hlsCustomName: document.getElementById("hlsCustomName"),
        hlsCustomUrl: document.getElementById("hlsCustomUrl"),
        btnPreviewDirectHls: document.getElementById("btnPreviewDirectHls"),
        btnConnectDirectHls: document.getElementById("btnConnectDirectHls"),
        hlsCustomFeedback: document.getElementById("hlsCustomFeedback"),

        // YouTube Tab Elements
        ytPresetSelect: document.getElementById("ytPresetSelect"),
        ytCustomName: document.getElementById("ytCustomName"),
        ytCustomUrl: document.getElementById("ytCustomUrl"),
        btnPreviewYouTube: document.getElementById("btnPreviewYouTube"),
        btnConnectYouTube: document.getElementById("btnConnectYouTube"),
        ytFeedback: document.getElementById("ytFeedback"),

        // Local Video Tab & Video Library Elements
        btnOpenUploadModal: document.getElementById("btnOpenUploadModal"),
        uploadVideoModal: document.getElementById("uploadVideoModal"),
        btnCloseUploadModal: document.getElementById("btnCloseUploadModal"),
        btnCancelUploadModal: document.getElementById("btnCancelUploadModal"),
        videoLibraryCountBadge: document.getElementById("videoLibraryCountBadge"),
        btnRefreshVideoLibrary: document.getElementById("btnRefreshVideoLibrary"),
        videoLibraryList: document.getElementById("videoLibraryList"),
        modalUploadFeedback: document.getElementById("modalUploadFeedback"),
        localUploadDropzone: document.getElementById("localUploadDropzone"),
        localVideoFileInput: document.getElementById("localVideoFileInput"),
        btnBrowseVideo: document.getElementById("btnBrowseVideo"),
        localFileInfoCard: document.getElementById("localFileInfoCard"),
        localFileNameText: document.getElementById("localFileNameText"),
        localFileSizeText: document.getElementById("localFileSizeText"),
        localFileStatusBadge: document.getElementById("localFileStatusBadge"),
        uploadProgressBarContainer: document.getElementById("uploadProgressBarContainer"),
        uploadProgressBarFill: document.getElementById("uploadProgressBarFill"),
        uploadProgressText: document.getElementById("uploadProgressText"),
        btnUploadAndConnect: document.getElementById("btnUploadAndConnect"),
        localVideoLoop: document.getElementById("localVideoLoop"),
        localFeedback: document.getElementById("localFeedback"),

        // Preview Modal Elements
        previewModal: document.getElementById("previewModal"),
        closePreviewBtn: document.getElementById("closePreviewBtn"),
        previewModalTitle: document.getElementById("previewModalTitle"),
        previewBadgeProvider: document.getElementById("previewBadgeProvider"),
        previewImage: document.getElementById("previewImage"),
        previewStream: document.getElementById("previewStream"),
        previewSpinner: document.getElementById("previewSpinner"),
        previewStreamUrl: document.getElementById("previewStreamUrl"),
        previewSourceType: document.getElementById("previewSourceType"),
        btnToggleLivePreview: document.getElementById("btnToggleLivePreview"),
        toggleLiveText: document.getElementById("toggleLiveText"),
        btnCancelPreview: document.getElementById("btnCancelPreview"),
        btnConfirmSelectCamera: document.getElementById("btnConfirmSelectCamera"),

        // Sidebar / Dashboard Elements
        backendUrlInput: document.getElementById("backendUrlInput"),
        cameraSelect: document.getElementById("cameraSelect"),
        switchCameraBtn: document.getElementById("switchCameraBtn"),
        cameraSwitchFeedback: document.getElementById("cameraSwitchFeedback"),
        sidebarConnStatus: document.getElementById("sidebarConnStatus"),
        pingLatency: document.getElementById("pingLatency"),
        statusBadge: document.getElementById("statusBadge"),
        alertBanner: document.getElementById("alertBanner"),

        // Video Feed Elements
        videoFeed: document.getElementById("videoFeed"),
        videoErrorOverlay: document.getElementById("videoErrorOverlay"),
        streamCamName: document.getElementById("streamCamName"),
        streamResolution: document.getElementById("streamResolution"),

        // Telemetry Elements
        telemActiveCam: document.getElementById("telemActiveCam"),
        metricPeopleCount: document.getElementById("metricPeopleCount"),
        metricCarCount: document.getElementById("metricCarCount"),
        metricCarLabel: document.getElementById("metricCarLabel"),
        zoneToggleCheckbox: document.getElementById("zoneToggleCheckbox"),
        zoneModeBadge: document.getElementById("zoneModeBadge"),
        metricDetections: document.getElementById("metricDetections"),
        metricTracks: document.getElementById("metricTracks"),
        metricProcessingFps: document.getElementById("metricProcessingFps"),
        metricStreamFps: document.getElementById("metricStreamFps"),
        metricYoloLatency: document.getElementById("metricYoloLatency"),
        metricPipelineLatency: document.getElementById("metricPipelineLatency"),

        // Hardware & Model Elements
        infoDevice: document.getElementById("infoDevice"),
        infoGpu: document.getElementById("infoGpu"),
        infoVram: document.getElementById("infoVram"),
        infoModel: document.getElementById("infoModel"),
        infoEventsToday: document.getElementById("infoEventsToday"),
        infoFilteredEvents: document.getElementById("infoFilteredEvents"),
        infoLastSavedCount: document.getElementById("infoLastSavedCount"),
        infoLastEvent: document.getElementById("infoLastEvent"),

        // Events Elements
        eventsContainer: document.getElementById("eventsContainer"),

        // Video Source Sidebar Elements
        sourceTypeSelect: document.getElementById("sourceTypeSelect"),
        sourceInput: document.getElementById("sourceInput"),
        sourceLoopCheckbox: document.getElementById("sourceLoopCheckbox"),
        applySourceBtn: document.getElementById("applySourceBtn"),
        sourceFeedback: document.getElementById("sourceFeedback"),

        // Target Registration & Management Elements
        btnOpenAddPersonModal: document.getElementById("btnOpenAddPersonModal"),
        addPersonModal: document.getElementById("addPersonModal"),
        btnCloseAddPersonModal: document.getElementById("btnCloseAddPersonModal"),
        btnCancelAddPersonModal: document.getElementById("btnCancelAddPersonModal"),
        targetNameInput: document.getElementById("targetNameInput"),
        targetColorSelect: document.getElementById("targetColorSelect"),
        targetFaceInput: document.getElementById("targetFaceInput"),
        targetFaceFilename: document.getElementById("targetFaceFilename"),
        targetFacePreviewContainer: document.getElementById("targetFacePreviewContainer"),
        targetFacePreview: document.getElementById("targetFacePreview"),
        targetThresholdInput: document.getElementById("targetThresholdInput"),
        addPersonFeedback: document.getElementById("addPersonFeedback"),
        registerTargetBtn: document.getElementById("registerTargetBtn"),
        targetFeedback: document.getElementById("targetFeedback"),
        targetCount: document.getElementById("targetCount"),
        targetsList: document.getElementById("targetsList")
    };

    /**
     * Resolve API endpoint URL.
     */
    function apiUrl(path) {
        return path;
    }

    /**
     * UI State Machine Transition Controller.
     */
    function setUiState(newState, meta) {
        state.uiState = newState;
        meta = meta || {};

        // Hide all screens first
        DOM.selectionScreen.style.display = "none";
        DOM.connectingScreen.style.display = "none";
        DOM.errorScreen.style.display = "none";
        DOM.monitoringScreen.style.display = "none";
        if (DOM.watchlistScreen) DOM.watchlistScreen.style.display = "none";
        if (DOM.cameraManagementScreen) DOM.cameraManagementScreen.style.display = "none";
        if (DOM.eventCenterScreen) DOM.eventCenterScreen.style.display = "none";

        if (newState === UI_STATE.SELECT_CAMERA) {
            DOM.selectionScreen.style.display = "flex";
            stopMonitoringTimers();
            stopConnectionPolling();
            updateActiveNavHighlight("camera");
            window.dattLoadMetrics = window.dattLoadMetrics || { startTime: performance.now() };
            window.dattLoadMetrics.uiShellReady = performance.now();
            fetchPublicCctvCameras();
            // Note: Defer fetchConfigCameras() to when YouTube tab is selected to keep initial load lightweight
        } else if (newState === UI_STATE.CONNECTING) {
            DOM.connectingScreen.style.display = "flex";
            stopMonitoringTimers();
            const camName = meta.name || "Camera";
            DOM.connectingTargetName.textContent = `Đang kết nối luồng "${camName}" và đợi khung hình đầu tiên...`;
            resetConnectingSteps();
        } else if (newState === UI_STATE.ERROR) {
            DOM.errorScreen.style.display = "flex";
            stopMonitoringTimers();
            stopConnectionPolling();
            DOM.errorMessageText.textContent = meta.message || "Không thể kết nối camera. Vui lòng kiểm tra lại luồng phát.";
            if (meta.debug) {
                DOM.errorDebugBox.style.display = "block";
                DOM.errorDebugBox.textContent = `Chi tiết lỗi: ${meta.debug}`;
            } else {
                DOM.errorDebugBox.style.display = "none";
            }
        } else if (newState === UI_STATE.MONITORING) {
            DOM.monitoringScreen.style.display = "block";
            stopConnectionPolling();
            updateActiveNavHighlight("dashboard");
            updateSourceHeader(meta.name, meta.provider, meta.source_type);
            triggerVideoRefresh();
            startMonitoringTimers();
        } else if (newState === UI_STATE.WATCHLIST) {
            if (DOM.watchlistScreen) DOM.watchlistScreen.style.display = "block";
            stopMonitoringTimers();
            stopConnectionPolling();
            updateActiveNavHighlight("watchlist");
            loadWatchlist();
        } else if (newState === UI_STATE.CAMERA_MANAGEMENT) {
            if (DOM.cameraManagementScreen) DOM.cameraManagementScreen.style.display = "block";
            stopMonitoringTimers();
            stopConnectionPolling();
            updateActiveNavHighlight("camera");
            loadManagementCameras();
        } else if (newState === UI_STATE.EVENT_CENTER) {
            if (DOM.eventCenterScreen) DOM.eventCenterScreen.style.display = "block";
            stopMonitoringTimers();
            stopConnectionPolling();
            updateActiveNavHighlight("events");
            loadEventCenterSummary();
            loadEventCenterEvents();
            populateEventCameraOptions();
        }
    }

    function resetConnectingSteps() {
        DOM.badgeStepReader.className = "status-pill active-step";
        DOM.badgeStepFrame.className = "status-pill";
        DOM.badgeStepAi.className = "status-pill";
    }

    function updateSourceHeader(name, provider, sourceType) {
        state.activeCameraName = name || state.activeCameraName || "Active Camera";
        state.activeProvider = provider || state.activeProvider || "Camera Source";
        state.activeSourceType = sourceType || state.activeSourceType || "HLS";

        DOM.dashHeaderCamName.textContent = state.activeCameraName;
        DOM.dashHeaderProvider.textContent = `${state.activeProvider} • ${state.activeSourceType}`;
        DOM.dashHeaderStatus.textContent = "● LIVE";
    }

    /**
     * Start/Stop Polling Timers.
     */
    function startMonitoringTimers() {
        stopMonitoringTimers();
        startFramePackets();
        pollEvents();
        loadTargets();
        state.eventsTimer = setInterval(pollEvents, CONFIG.eventsIntervalMs);
    }

    function stopMonitoringTimers() {
        stopFramePackets();
        if (state.telemetryTimer) {
            clearInterval(state.telemetryTimer);
            state.telemetryTimer = null;
        }
        if (state.eventsTimer) {
            clearInterval(state.eventsTimer);
            state.eventsTimer = null;
        }
    }

    function stopConnectionPolling() {
        if (state.connectionTimer) {
            clearInterval(state.connectionTimer);
            state.connectionTimer = null;
        }
    }

    /**
     * Switch Tabs on Camera Selection Screen.
     */
    function initTabs() {
        const tabBtns = document.querySelectorAll(".source-tab-btn");
        tabBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const targetId = btn.getAttribute("data-tab");
                tabBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                document.querySelectorAll(".tab-pane").forEach(pane => {
                    pane.classList.remove("active");
                });
                const targetPane = document.getElementById(targetId);
                if (targetPane) {
                    targetPane.classList.add("active");
                }
                if (targetId === "tab-youtube") {
                    fetchConfigCameras();
                }
                if (targetId === "tab-local") {
                    loadVideoLibrary();
                }
            });
        });
    }

    /**
     * Provider Selector (Seattle SDOT vs Caltrans).
     */
    function initProviderSelector() {
        const providerBtns = document.querySelectorAll(".provider-btn");
        providerBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const provider = btn.getAttribute("data-provider");
                providerBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                state.cctvProvider = provider;
                if (DOM.cctvSearchInput) {
                    DOM.cctvSearchInput.value = "";
                }
                fetchPublicCctvCameras(false);
            });
        });
    }

    const PLACEHOLDER_THUMBNAIL = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='180' viewBox='0 0 320 180'%3E%3Crect width='100%25' height='100%25' fill='%23131722'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%2364748b' font-family='sans-serif' font-size='12'%3E%F0%9F%93%B7 CCTV Camera%3C/text%3E%3C/svg%3E";

    let cctvThumbObserver = null;
    function setupThumbnailObserver() {
        if (cctvThumbObserver) {
            cctvThumbObserver.disconnect();
        }
        if (!('IntersectionObserver' in window)) {
            document.querySelectorAll(".cctv-thumb-img[data-src]").forEach(img => {
                const src = img.getAttribute("data-src");
                if (src) {
                    img.src = src;
                    img.removeAttribute("data-src");
                }
            });
            return;
        }

        cctvThumbObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    const src = img.getAttribute("data-src");
                    if (src) {
                        img.src = src;
                        img.removeAttribute("data-src");
                    }
                    observer.unobserve(img);
                }
            });
        }, { rootMargin: "150px 0px" });

        document.querySelectorAll(".cctv-thumb-img[data-src]").forEach(img => {
            cctvThumbObserver.observe(img);
        });
    }

    /**
     * Fetch & Render Public CCTV Cameras (Seattle SDOT or Caltrans).
     */
    async function fetchPublicCctvCameras(forceRefresh) {
        try {
            DOM.cctvCountBadge.textContent = "Đang tải danh mục...";
            const provider = state.cctvProvider || "seattle";
            const refreshParam = forceRefresh ? "&refresh=true" : "";
            const url = apiUrl(`/api/public_cameras?provider=${encodeURIComponent(provider)}${refreshParam}`);
            const fetchStart = performance.now();
            const resp = await fetch(url);
            if (resp.ok) {
                const data = await resp.json();
                state.cctvCameras = data.cameras || [];
                const providerLabel = provider === "seattle" ? "Seattle SDOT" : "Caltrans";
                DOM.cctvCountBadge.textContent = `Hiển thị ${state.cctvCameras.length} camera (${providerLabel})`;

                if (window.dattLoadMetrics) {
                    window.dattLoadMetrics.catalogFetchedTime = performance.now();
                    const fetchElapsed = (window.dattLoadMetrics.catalogFetchedTime - fetchStart).toFixed(1);
                    console.log(`[DATT Perf] CCTV metadata (${provider}) fetched in ${fetchElapsed} ms`);
                }

                renderCctvCards(state.cctvCameras);
            } else {
                DOM.cctvCountBadge.textContent = "Lỗi tải camera";
                DOM.cctvCardsGrid.innerHTML = `
                    <div class="cards-loading-state">
                        <p style="color:#ef4444;">⚠️ Không thể tải danh mục camera CCTV. Vui lòng bấm làm mới.</p>
                    </div>`;
            }
        } catch (err) {
            DOM.cctvCountBadge.textContent = "Lỗi kết nối";
            DOM.cctvCardsGrid.innerHTML = `
                <div class="cards-loading-state">
                    <p style="color:#ef4444;">⚠️ Lỗi kết nối mạng: ${err.message}</p>
                </div>`;
        }
    }

    /**
     * Render CCTV Cards in Responsive Grid with Lazy-Loaded Thumbnails.
     */
    function renderCctvCards(cameras) {
        if (!cameras || cameras.length === 0) {
            DOM.cctvCardsGrid.innerHTML = `
                <div class="cards-loading-state">
                    <p>Không tìm thấy camera nào phù hợp với từ khóa.</p>
                </div>`;
            return;
        }

        const providerDefault = state.cctvProvider === "seattle" ? "Seattle SDOT" : "Caltrans";

        DOM.cctvCardsGrid.innerHTML = cameras.map(cam => {
            const safeName = escapeHtml(cam.name);
            const safeId = escapeHtml(cam.id);
            const safeStream = escapeHtml(cam.stream_url);
            const safeSnapshot = escapeHtml(cam.snapshot_url || "");
            const provider = escapeHtml(cam.provider || providerDefault);
            const sourceType = escapeHtml(cam.source_type || "direct_hls");
            const resBadge = cam.resolution ? `<span class="cctv-tag font-mono">${escapeHtml(cam.resolution)}</span>` : "";

            // Use lightweight server-cached thumbnail endpoint with HLS 1-frame fallback
            const thumbUrl = `/api/camera_thumbnail?camera_id=${encodeURIComponent(cam.id)}&provider=${encodeURIComponent(provider)}&snapshot_url=${encodeURIComponent(cam.snapshot_url || '')}&stream_url=${encodeURIComponent(cam.stream_url || '')}`;

            return `
                <div class="cctv-card" id="card_${safeId}">
                    <div class="cctv-thumb-box">
                        <img src="${PLACEHOLDER_THUMBNAIL}"
                             data-src="${thumbUrl}"
                             alt="${safeName}"
                             class="cctv-thumb-img"
                             loading="lazy"
                             onerror="this.onerror=null;this.src='${PLACEHOLDER_THUMBNAIL}';">
                        <div class="cctv-status-badge">
                            <span class="pulse-dot"></span> LIVE
                        </div>
                    </div>
                    <div class="cctv-card-body">
                        <h4 class="cctv-card-title">${safeName}</h4>
                        <div class="cctv-meta-row">
                            <span>Provider: <strong>${provider}</strong></span>
                            ${resBadge}
                            <span class="cctv-tag">${sourceType}</span>
                        </div>
                        <div class="cctv-card-actions">
                            <button type="button" class="btn-preview-card"
                                    onclick="window.dattPreviewCamera('${safeId}', '${safeName}', '${safeStream}', '${safeSnapshot}', '${provider}', '${sourceType}')">
                                👁️ Xem thử
                            </button>
                            <button type="button" class="btn-select-card"
                                    onclick="window.dattSelectCamera('${safeName}', '${safeStream}', '${sourceType}', '${provider}')">
                                ▶️ Chọn
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join("");

        // Setup lazy loading for visible thumbnails
        setupThumbnailObserver();

        if (window.dattLoadMetrics) {
            window.dattLoadMetrics.cardsRenderedTime = performance.now();
            const totalElapsed = (window.dattLoadMetrics.cardsRenderedTime - window.dattLoadMetrics.startTime).toFixed(1);
            console.log(`[DATT Perf] Initial CCTV cards rendered in ${totalElapsed} ms`);
        }
    }

    /**
     * Real-time Local Search Filter for CCTV Cards.
     */
    function initSearch() {
        DOM.cctvSearchInput.addEventListener("input", (e) => {
            const query = e.target.value.trim().toLowerCase();
            if (!query) {
                DOM.cctvCountBadge.textContent = `Hiển thị ${state.cctvCameras.length} camera`;
                renderCctvCards(state.cctvCameras);
                return;
            }

            const filtered = state.cctvCameras.filter(c => {
                const name = (c.name || "").toLowerCase();
                const streamName = (c.stream_name || "").toLowerCase();
                const district = (c.district || "").toLowerCase();
                const county = (c.county || "").toLowerCase();
                const city = (c.city || "").toLowerCase();
                return (
                    name.includes(query) ||
                    streamName.includes(query) ||
                    district.includes(query) ||
                    county.includes(query) ||
                    city.includes(query)
                );
            });

            DOM.cctvCountBadge.textContent = `Tìm thấy ${filtered.length} / ${state.cctvCameras.length} camera`;
            renderCctvCards(filtered);
        });

        DOM.refreshCatalogBtn.addEventListener("click", () => {
            fetchPublicCctvCameras(true);
        });
    }

    /**
     * Preview Modal Controller (Snapshot first, optional live stream).
     */
    window.dattPreviewCamera = function (id, name, streamUrl, snapshotUrl, provider, sourceType) {
        state.previewingCamera = { id, name, streamUrl, snapshotUrl, provider, sourceType };
        state.isPreviewLive = false;

        DOM.previewModalTitle.textContent = `Xem trước: ${name}`;
        DOM.previewBadgeProvider.textContent = provider || "Caltrans";
        DOM.previewStreamUrl.textContent = streamUrl || "--";
        DOM.previewSourceType.textContent = sourceType || "Direct HLS";

        // Snapshot first
        DOM.previewStream.style.display = "none";
        DOM.previewStream.src = "";
        DOM.previewImage.style.display = "block";
        DOM.previewSpinner.style.display = "none";
        DOM.toggleLiveText.textContent = "Phát trực tiếp";

        const proxySnapshot = snapshotUrl ? `/api/camera_snapshot?url=${encodeURIComponent(snapshotUrl)}` : "";
        DOM.previewImage.src = proxySnapshot || "/static/favicon.ico";

        DOM.previewModal.style.display = "flex";
    };

    async function closePreview() {
        DOM.previewModal.style.display = "none";
        DOM.previewStream.src = "";
        DOM.previewStream.style.display = "none";
        state.isPreviewLive = false;
        state.previewingCamera = null;

        // Clean up preview resources on backend
        try {
            await fetch(apiUrl("/api/stop_preview"), { method: "POST" });
        } catch (e) {
            // suppress
        }
    }

    async function toggleLivePreview() {
        if (!state.previewingCamera || !state.previewingCamera.streamUrl) return;

        if (!state.isPreviewLive) {
            // Switch to Live Preview
            state.isPreviewLive = true;
            DOM.previewImage.style.display = "none";
            DOM.previewStream.style.display = "block";
            DOM.previewSpinner.style.display = "flex";
            DOM.previewLoadingText.textContent = "Đang kết nối luồng xem trước...";
            DOM.toggleLiveText.textContent = "Xem ảnh chụp (Snapshot)";

            DOM.previewStream.onload = () => {
                DOM.previewSpinner.style.display = "none";
            };

            const streamUrl = state.previewingCamera.streamUrl;
            const provider = state.previewingCamera.provider || "";
            DOM.previewStream.src = `/api/preview_feed?url=${encodeURIComponent(streamUrl)}&provider=${encodeURIComponent(provider)}&t=${Date.now()}`;
        } else {
            // Switch back to Snapshot
            state.isPreviewLive = false;
            DOM.previewStream.style.display = "none";
            DOM.previewStream.src = "";
            DOM.previewImage.style.display = "block";
            DOM.previewSpinner.style.display = "none";
            DOM.toggleLiveText.textContent = "Phát trực tiếp";

            try {
                await fetch(apiUrl("/api/stop_preview"), { method: "POST" });
            } catch (e) {}
        }
    }

    /**
     * Primary Camera Selection & Connection Verification Sequence.
     * Criteria: frames_received > 0, frame_age_seconds < 5.0, stream_alive is true.
     */
    window.dattSelectCamera = async function (name, streamUrl, sourceType, provider, videoSourceId, loop, cameraId) {
        await closePreview();

        const isLoop = (loop !== undefined && loop !== null) ? Boolean(loop) : (DOM.localVideoLoop ? DOM.localVideoLoop.checked : true);
        const sourceData = {
            name: name,
            source: streamUrl,
            stream_url: streamUrl,
            source_type: sourceType || "direct_hls",
            provider: provider || "Caltrans",
            video_source_id: videoSourceId || null,
            camera_id: cameraId || null,
            loop: isLoop
        };
        state.connectingSourceData = sourceData;

        // Transition to CONNECTING state
        setUiState(UI_STATE.CONNECTING, { name: name });

        try {
            // 1. Tell backend to stop old source & start new source
            const resp = await fetch(apiUrl("/api/select_source"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    source_type: sourceData.source_type,
                    source: sourceData.source,
                    url: sourceData.source,
                    name: sourceData.name,
                    provider: sourceData.provider,
                    video_source_id: sourceData.video_source_id,
                    camera_id: sourceData.camera_id,
                    loop: sourceData.loop
                })
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                setUiState(UI_STATE.ERROR, {
                    message: "Không thể gửi yêu cầu kết nối camera tới máy chủ.",
                    debug: errData.message || resp.statusText
                });
                return;
            }

            DOM.badgeStepReader.className = "status-pill active-step";

            // 2. Poll /api/source_status until verified or timeout
            pollConnectionVerification(sourceData);

        } catch (err) {
            setUiState(UI_STATE.ERROR, {
                message: "Lỗi mạng khi kết nối camera.",
                debug: err.message
            });
        }
    };

    function pollConnectionVerification(sourceData) {
        stopConnectionPolling();
        const startConnectTime = Date.now();

        state.connectionTimer = setInterval(async () => {
            const elapsed = Date.now() - startConnectTime;

            // Timeout check
            if (elapsed > CONFIG.connectionTimeoutMs) {
                stopConnectionPolling();
                setUiState(UI_STATE.ERROR, {
                    message: `Không nhận được khung hình từ camera "${sourceData.name}" sau 15 giây.`,
                    debug: "Connection verification timed out (first frame not arrived)"
                });
                return;
            }

            try {
                const resp = await fetch(apiUrl("/api/source_status"));
                if (resp.ok) {
                    const data = await resp.json();

                    // Step badge updates
                    if (data.status === "RUNNING" || data.status === "SWITCHING") {
                        DOM.badgeStepReader.className = "status-pill active-step";
                    }
                    if (data.frames_received > 0) {
                        DOM.badgeStepFrame.className = "status-pill active-step";
                    }

                    // Successful Connection Criteria:
                    // 1. frames_received > 0
                    // 2. frame_age_seconds is recent (< 5.0s)
                    // 3. stream_alive is true
                    // 4. status is RUNNING
                    const framesOk = (data.frames_received > 0);
                    const ageOk = (data.frame_age_seconds <= 5.0);
                    const aliveOk = (data.stream_alive === true);
                    const statusOk = (data.status === "RUNNING");

                    if (framesOk && ageOk && aliveOk && statusOk) {
                        DOM.badgeStepAi.className = "status-pill active-step";
                        stopConnectionPolling();

                        // Short delay to let AI pipeline finish first inference frame cleanly
                        setTimeout(() => {
                            setUiState(UI_STATE.MONITORING, {
                                name: sourceData.name,
                                provider: sourceData.provider,
                                source_type: sourceData.source_type
                            });
                        }, 400);
                        return;
                    }

                    if (data.status === "VIDEO_FINISHED") {
                        stopConnectionPolling();
                        setUiState(UI_STATE.MONITORING, {
                            name: sourceData.name,
                            provider: sourceData.provider,
                            source_type: sourceData.source_type
                        });
                        return;
                    }

                    if (data.status === "ERROR") {
                        stopConnectionPolling();
                        const reason = data.error_reason || "Mất kết nối luồng";
                        const isAuth = reason.includes("AUTH/ANTI_BOT") || reason.toLowerCase().includes("not a bot");
                        setUiState(UI_STATE.ERROR, {
                            message: isAuth
                                ? `YouTube yêu cầu xác minh bot ("Sign in to confirm you're not a bot"). Đã dừng kết nối và không retry.`
                                : `Camera báo lỗi: ${reason}`,
                            debug: reason
                        });
                        return;
                    }
                }
            } catch (err) {
                // Ignore transient network blips during polling
            }
        }, CONFIG.sourceStatusPollMs);
    }

    /**
     * Stop Camera & Return to Selection.
     */
    async function stopActiveCameraAndReturn() {
        try {
            await fetch(apiUrl("/api/stop_camera"), { method: "POST" });
        } catch (e) {}

        state.activeCameraId = "";
        state.activeCameraName = "";
        state.connectingSourceData = null;
        setUiState(UI_STATE.SELECT_CAMERA);
    }

    /**
     * Manual Direct HLS Tab Setup.
     */
    function initDirectHlsTab() {
        DOM.btnPreviewDirectHls.addEventListener("click", () => {
            const url = DOM.hlsCustomUrl.value.trim();
            const name = DOM.hlsCustomName.value.trim() || "Custom HLS Camera";
            if (!url) {
                DOM.hlsCustomFeedback.className = "feedback-msg error";
                DOM.hlsCustomFeedback.textContent = "Vui lòng nhập URL stream HLS (.m3u8).";
                return;
            }
            DOM.hlsCustomFeedback.textContent = "";
            window.dattPreviewCamera("custom_hls", name, url, "", "Direct HLS", "direct_hls");
        });

        DOM.btnConnectDirectHls.addEventListener("click", () => {
            const url = DOM.hlsCustomUrl.value.trim();
            const name = DOM.hlsCustomName.value.trim() || "Custom HLS Camera";
            if (!url) {
                DOM.hlsCustomFeedback.className = "feedback-msg error";
                DOM.hlsCustomFeedback.textContent = "Vui lòng nhập URL stream HLS (.m3u8).";
                return;
            }
            DOM.hlsCustomFeedback.textContent = "";
            window.dattSelectCamera(name, url, "direct_hls", "Direct HLS");
        });
    }

    /**
     * YouTube Live Tab Setup.
     */
    async function fetchConfigCameras() {
        try {
            const resp = await fetch(apiUrl("/cameras"));
            if (resp.ok) {
                const data = await resp.json();
                const cameras = data.cameras || [];

                DOM.ytPresetSelect.innerHTML = '<option value="">-- Chọn camera định cấu hình sẵn --</option>';
                cameras.forEach(c => {
                    const opt = document.createElement("option");
                    opt.value = c.id;
                    opt.textContent = `${c.name} (${c.type})`;
                    opt.dataset.url = c.url;
                    opt.dataset.name = c.name;
                    opt.dataset.type = c.type;
                    DOM.ytPresetSelect.appendChild(opt);
                });

                // Also populate sidebar select
                DOM.cameraSelect.innerHTML = "";
                cameras.forEach(c => {
                    const opt = document.createElement("option");
                    opt.value = c.id;
                    opt.textContent = `${c.name} (${c.type})`;
                    DOM.cameraSelect.appendChild(opt);
                });
            }
        } catch (e) {}
    }

    function initYouTubeTab() {
        DOM.ytPresetSelect.addEventListener("change", (e) => {
            const selectedOpt = e.target.selectedOptions[0];
            if (selectedOpt && selectedOpt.dataset.url) {
                DOM.ytCustomName.value = selectedOpt.dataset.name || "";
                DOM.ytCustomUrl.value = selectedOpt.dataset.url || "";
            }
        });

        DOM.btnPreviewYouTube.addEventListener("click", () => {
            const url = DOM.ytCustomUrl.value.trim();
            const name = DOM.ytCustomName.value.trim() || "YouTube Stream";
            if (!url) {
                DOM.ytFeedback.className = "feedback-msg error";
                DOM.ytFeedback.textContent = "Vui lòng chọn hoặc nhập liên kết YouTube.";
                return;
            }
            DOM.ytFeedback.textContent = "";
            window.dattPreviewCamera("custom_yt", name, url, "", "YouTube", "youtube");
        });

        DOM.btnConnectYouTube.addEventListener("click", () => {
            const url = DOM.ytCustomUrl.value.trim();
            const name = DOM.ytCustomName.value.trim() || "YouTube Stream";
            if (!url) {
                DOM.ytFeedback.className = "feedback-msg error";
                DOM.ytFeedback.textContent = "Vui lòng chọn hoặc nhập liên kết YouTube.";
                return;
            }
            DOM.ytFeedback.textContent = "";
            window.dattSelectCamera(name, url, "youtube", "YouTube Live");
        });
    }

    /**
     * Local Video Tab Setup (Video Library & Persistent Storage Flow).
     */
    async function loadVideoLibrary() {
        if (!DOM.videoLibraryList) return;
        try {
            const resp = await fetch(apiUrl("/api/video_sources"));
            if (resp.ok) {
                const data = await resp.json();
                renderVideoLibrary(data.sources || []);
            }
        } catch (e) {
            console.warn("Failed to load video library:", e);
        }
    }

    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return "0 Bytes";
        const k = 1024;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
    }

    function renderVideoLibrary(videos) {
        if (DOM.videoLibraryCountBadge) {
            DOM.videoLibraryCountBadge.textContent = `${videos.length} video${videos.length === 1 ? '' : 's'}`;
        }
        if (!DOM.videoLibraryList) return;
        if (videos.length === 0) {
            DOM.videoLibraryList.innerHTML = `
                <div class="video-library-empty">
                    <span class="empty-icon">📂</span>
                    <p>Chưa có video nào trong thư viện.</p>
                    <p style="font-size: 0.8rem; color: #94a3b8;">Bấm "+ Upload Video" ở trên để tải lên video MP4 mới.</p>
                </div>
            `;
            return;
        }

        DOM.videoLibraryList.innerHTML = videos.map(v => {
            const sizeStr = v.file_size_bytes ? formatBytes(v.file_size_bytes) : "";
            const durationSec = v.duration_sec !== undefined && v.duration_sec !== null ? v.duration_sec : v.duration_seconds;
            const durationStr = durationSec ? `${Math.round(durationSec)}s` : "";
            const resStr = (v.width && v.height) ? `${v.width}x${v.height}` : "";
            const metaBadges = [sizeStr, durationStr, resStr].filter(Boolean).map(m => `<span class="video-card-badge">${escapeHtml(m)}</span>`).join("");
            const dateStr = v.created_at ? new Date(v.created_at).toLocaleString() : "";
            const safeName = escapeHtml(v.original_filename || "Video");
            const safePath = escapeHtml(v.storage_path || "");
            const safeId = escapeHtml(v.id || "");
            const rawStatus = (v.status || "ready").toUpperCase();
            const statusClass = rawStatus === "READY" ? "badge-status-ready" : "badge-status-other";

            return `
                <div class="video-card" data-id="${safeId}">
                    <div class="video-card-header">
                        <div class="video-card-icon">🎬</div>
                        <div class="video-card-info">
                            <div class="video-card-title" title="${safeName}">${safeName}</div>
                            <div class="video-card-status-row">
                                <span class="video-status-badge ${statusClass}">● ${rawStatus}</span>
                                ${dateStr ? `<span class="video-card-date" title="Ngày tải lên">${dateStr}</span>` : ""}
                            </div>
                        </div>
                    </div>
                    ${metaBadges ? `<div class="video-card-meta">${metaBadges}</div>` : ""}
                    <div class="video-card-actions">
                        <button type="button" class="primary-btn btn-sm btn-select-video" title="Sử dụng video này chạy AI" onclick="window.dattSelectLibraryVideo('${safeName}', '${safePath}', '${safeId}')">
                            <span class="btn-icon">▶️</span> Select / Use Video
                        </button>
                        <button type="button" class="secondary-btn btn-sm btn-delete-video" title="Xóa video khỏi hệ thống" onclick="window.dattDeleteVideoSource('${safeId}')">
                            🗑️ Delete
                        </button>
                    </div>
                </div>
            `;
        }).join("");
    }

    window.dattSelectLibraryVideo = function(name, path, id) {
        const loop = DOM.localVideoLoop ? DOM.localVideoLoop.checked : true;
        window.dattSelectCamera(`Local: ${name}`, path, "local", "Local Video", id, loop);
    };

    window.dattDeleteVideoSource = async function(id) {
        if (!confirm("Bạn có chắc chắn muốn xóa video này khỏi hệ thống và cơ sở dữ liệu?")) return;
        try {
            const resp = await fetch(apiUrl(`/api/video_sources/${encodeURIComponent(id)}`), {
                method: "DELETE"
            });
            if (resp.ok) {
                await loadVideoLibrary();
            } else {
                const err = await resp.json().catch(() => ({}));
                alert(`Không thể xóa: ${err.message || resp.statusText}`);
            }
        } catch (e) {
            alert(`Lỗi mạng: ${e.message}`);
        }
    };

    function initLocalVideoTab() {
        let selectedFile = null;

        // Modal triggers
        if (DOM.btnOpenUploadModal && DOM.uploadVideoModal) {
            DOM.btnOpenUploadModal.addEventListener("click", () => {
                DOM.uploadVideoModal.style.display = "flex";
                if (DOM.modalUploadFeedback) DOM.modalUploadFeedback.textContent = "";
                if (DOM.uploadProgressBarContainer) DOM.uploadProgressBarContainer.style.display = "none";
                if (DOM.localFileInfoCard) DOM.localFileInfoCard.style.display = "none";
                if (DOM.btnUploadAndConnect) DOM.btnUploadAndConnect.disabled = true;
                selectedFile = null;
                if (DOM.localVideoFileInput) DOM.localVideoFileInput.value = "";
            });
        }

        const closeUploadModal = () => {
            if (DOM.uploadVideoModal) DOM.uploadVideoModal.style.display = "none";
        };

        if (DOM.btnCloseUploadModal) DOM.btnCloseUploadModal.addEventListener("click", closeUploadModal);
        if (DOM.btnCancelUploadModal) DOM.btnCancelUploadModal.addEventListener("click", closeUploadModal);

        if (DOM.btnRefreshVideoLibrary) {
            DOM.btnRefreshVideoLibrary.addEventListener("click", () => loadVideoLibrary());
        }

        function handleFileSelection(file) {
            if (!file) return;
            const allowed = [".mp4", ".mov", ".mkv", ".avi"];
            const ext = "." + file.name.split(".").pop().toLowerCase();
            if (!allowed.includes(ext)) {
                if (DOM.modalUploadFeedback) {
                    DOM.modalUploadFeedback.className = "feedback-msg error";
                    DOM.modalUploadFeedback.textContent = `Định dạng tệp "${ext}" không được hỗ trợ. Vui lòng chọn MP4, MOV, MKV hoặc AVI.`;
                }
                return;
            }

            selectedFile = file;
            if (DOM.localFileNameText) DOM.localFileNameText.textContent = file.name;
            if (DOM.localFileSizeText) DOM.localFileSizeText.textContent = formatBytes(file.size);
            if (DOM.localFileStatusBadge) {
                DOM.localFileStatusBadge.textContent = "Sẵn sàng upload";
                DOM.localFileStatusBadge.className = "file-status-badge";
            }
            if (DOM.localFileInfoCard) DOM.localFileInfoCard.style.display = "block";
            if (DOM.uploadProgressBarContainer) DOM.uploadProgressBarContainer.style.display = "none";
            if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = "0%";
            if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = "0%";
            if (DOM.btnUploadAndConnect) DOM.btnUploadAndConnect.disabled = false;
            if (DOM.modalUploadFeedback) DOM.modalUploadFeedback.textContent = "";
        }

        if (DOM.btnBrowseVideo) {
            DOM.btnBrowseVideo.addEventListener("click", () => {
                if (DOM.localVideoFileInput) DOM.localVideoFileInput.click();
            });
        }

        if (DOM.localVideoFileInput) {
            DOM.localVideoFileInput.addEventListener("change", (e) => {
                const file = e.target.files[0];
                handleFileSelection(file);
            });
        }

        if (DOM.localUploadDropzone) {
            DOM.localUploadDropzone.addEventListener("dragover", (e) => {
                e.preventDefault();
                DOM.localUploadDropzone.classList.add("dragover");
            });

            DOM.localUploadDropzone.addEventListener("dragleave", (e) => {
                e.preventDefault();
                DOM.localUploadDropzone.classList.remove("dragover");
            });

            DOM.localUploadDropzone.addEventListener("drop", (e) => {
                e.preventDefault();
                DOM.localUploadDropzone.classList.remove("dragover");
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    handleFileSelection(e.dataTransfer.files[0]);
                }
            });
        }

        if (DOM.btnUploadAndConnect) {
            DOM.btnUploadAndConnect.addEventListener("click", () => {
                if (!selectedFile) {
                    if (DOM.modalUploadFeedback) {
                        DOM.modalUploadFeedback.className = "feedback-msg error";
                        DOM.modalUploadFeedback.textContent = "Vui lòng chọn tệp video trước khi upload.";
                    }
                    return;
                }

                DOM.btnUploadAndConnect.disabled = true;
                if (DOM.uploadProgressBarContainer) DOM.uploadProgressBarContainer.style.display = "flex";
                if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = "0%";
                if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = "0%";
                if (DOM.localFileStatusBadge) {
                    DOM.localFileStatusBadge.textContent = "Đang tải lên...";
                    DOM.localFileStatusBadge.className = "file-status-badge uploading";
                }
                if (DOM.modalUploadFeedback) DOM.modalUploadFeedback.textContent = "";

                const formData = new FormData();
                formData.append("file", selectedFile);

                const xhr = new XMLHttpRequest();
                xhr.open("POST", apiUrl("/api/upload_video"), true);

                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable) {
                        const percent = Math.round((event.loaded / event.total) * 100);
                        if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = `${percent}%`;
                        if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = `${percent}%`;
                    }
                };

                xhr.onload = async () => {
                    if (xhr.status === 200) {
                        try {
                            const res = JSON.parse(xhr.responseText);
                            if (res.status === "ok") {
                                if (DOM.localFileStatusBadge) {
                                    DOM.localFileStatusBadge.textContent = "Upload thành công ✓";
                                    DOM.localFileStatusBadge.className = "file-status-badge success";
                                }
                                if (DOM.uploadProgressBarFill) DOM.uploadProgressBarFill.style.width = "100%";
                                if (DOM.uploadProgressText) DOM.uploadProgressText.textContent = "100%";

                                // Refresh video library automatically from backend
                                await loadVideoLibrary();

                                // Close modal after brief pause
                                setTimeout(() => {
                                    closeUploadModal();
                                }, 500);
                                return;
                            }
                        } catch (e) {}
                    }

                    // Error handling
                    DOM.btnUploadAndConnect.disabled = false;
                    if (DOM.localFileStatusBadge) {
                        DOM.localFileStatusBadge.textContent = "Upload thất bại ✗";
                        DOM.localFileStatusBadge.className = "file-status-badge error";
                    }
                    let errorMsg = "Tải tệp video thất bại.";
                    try {
                        const err = JSON.parse(xhr.responseText);
                        if (err.message) errorMsg = err.message;
                    } catch (e) {}
                    if (DOM.modalUploadFeedback) {
                        DOM.modalUploadFeedback.className = "feedback-msg error";
                        DOM.modalUploadFeedback.textContent = errorMsg;
                    }
                };

                xhr.onerror = () => {
                    DOM.btnUploadAndConnect.disabled = false;
                    if (DOM.localFileStatusBadge) {
                        DOM.localFileStatusBadge.textContent = "Lỗi kết nối ✗";
                        DOM.localFileStatusBadge.className = "file-status-badge error";
                    }
                    if (DOM.modalUploadFeedback) {
                        DOM.modalUploadFeedback.className = "feedback-msg error";
                        DOM.modalUploadFeedback.textContent = "Lỗi mạng khi tải lên tệp video.";
                    }
                };

                xhr.send(formData);
            });
        }
    }

    /**
     * Preview Modal Actions Setup.
     */
    function initPreviewModal() {
        DOM.closePreviewBtn.addEventListener("click", closePreview);
        DOM.btnCancelPreview.addEventListener("click", closePreview);
        DOM.btnToggleLivePreview.addEventListener("click", toggleLivePreview);

        DOM.btnConfirmSelectCamera.addEventListener("click", () => {
            if (state.previewingCamera) {
                const cam = state.previewingCamera;
                window.dattSelectCamera(cam.name, cam.streamUrl, cam.sourceType, cam.provider);
            }
        });

        // Close on escape key
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && DOM.previewModal.style.display !== "none") {
                closePreview();
            }
        });
    }

    /**
     * Error & Retrying Actions Setup.
     */
    function initErrorActions() {
        DOM.btnRetryConnection.addEventListener("click", () => {
            if (state.connectingSourceData) {
                const d = state.connectingSourceData;
                window.dattSelectCamera(d.name, d.source, d.source_type, d.provider);
            } else {
                setUiState(UI_STATE.SELECT_CAMERA);
            }
        });

        DOM.btnBackToSelection.addEventListener("click", () => {
            setUiState(UI_STATE.SELECT_CAMERA);
        });

        // Switch camera button from monitoring dashboard
        DOM.btnSwitchCameraFromDash.addEventListener("click", stopActiveCameraAndReturn);
    }

    /**
     * Video Stream MJPEG Reconnect Logic.
     */
    let frameEpoch = 0;
    let frameController = null;
    let frameTimer = null;

    function stopFramePackets() {
        frameEpoch++;
        if (frameController) frameController.abort();
        frameController = null;
        clearTimeout(frameTimer);
    }

    function triggerVideoRefresh() {
        // startMonitoringTimers owns the single image/metrics request loop.
        stopFramePackets();
        const ctx = DOM.videoFeed.getContext("2d");
        ctx.clearRect(0, 0, DOM.videoFeed.width, DOM.videoFeed.height);
        for (const element of [DOM.metricPeopleCount, DOM.metricCarCount,
            DOM.metricDetections, DOM.metricTracks]) {
            if (element) element.textContent = "?";
        }
    }

    function setupVideoStream() {}
    function pollTelemetry() { /* Compatibility alias for telemetry streaming */ }

    function startFramePackets() {
        stopFramePackets();
        const epoch = frameEpoch;
        let lastKey = null;
        async function nextFrame() {
            if (epoch !== frameEpoch || state.uiState !== UI_STATE.MONITORING) return;
            const started = performance.now();
            const controller = new AbortController();
            frameController = controller;
            const timeout = setTimeout(() => controller.abort(), 5000);
            let failed = false;
            try {
                const response = await fetch(apiUrl("/frame_packet"), {
                    cache: "no-store", signal: controller.signal
                });
                if (epoch !== frameEpoch) return;
                if (response.status === 204) {
                    DOM.videoErrorOverlay.style.display = "flex";
                    return;
                }
                if (!response.ok) throw new Error(`Frame HTTP ${response.status}`);
                const metrics = JSON.parse(response.headers.get("X-Frame-Telemetry"));
                const key = `${metrics.source_generation}:${metrics.frame_id}`;
                const blob = await response.blob();
                if (epoch !== frameEpoch) return;
                if (key !== lastKey) {
                    const bitmap = await createImageBitmap(blob);
                    try {
                        await new Promise(resolve => requestAnimationFrame(() => {
                            try {
                                if (epoch !== frameEpoch) return;
                                const canvas = DOM.videoFeed;
                                if (canvas.width !== bitmap.width) canvas.width = bitmap.width;
                                if (canvas.height !== bitmap.height) canvas.height = bitmap.height;
                                canvas.getContext("2d").drawImage(bitmap, 0, 0);
                                applyTelemetry(metrics);
                                canvas.dataset.frameId = String(metrics.frame_id);
                                canvas.dataset.sourceGeneration = String(metrics.source_generation);
                                lastKey = key;
                            } finally { resolve(); }
                        }));
                    } finally { bitmap.close(); }
                }
                if (epoch !== frameEpoch) return;
                DOM.videoErrorOverlay.style.display = "none";
                DOM.pingLatency.textContent = `${Math.round(performance.now() - started)} ms`;
                state.consecutiveErrors = 0;
            } catch (error) {
                failed = true;
                if (epoch === frameEpoch) {
                    DOM.videoErrorOverlay.style.display = "flex";
                    handleTelemetryError();
                }
            } finally {
                clearTimeout(timeout);
                if (epoch === frameEpoch) {
                    frameTimer = setTimeout(nextFrame, failed ? 500 : Math.max(0, 33 - (performance.now() - started)));
                }
            }
        }
        nextFrame();
    }

    function applyTelemetry(data) {
        const status = state.isSwitchingCamera ? "SWITCHING" : (data.camera_status || data.status || "DISCONNECTED");
        updateStatus(status, data.error_message);

        const camName = data.camera_name || data.camera_id || state.activeCameraName || "Camera";
        DOM.telemActiveCam.textContent = camName;
        DOM.streamCamName.textContent = `Camera: ${camName}`;
        DOM.streamResolution.textContent = data.input_size || "640x640";

        DOM.metricPeopleCount.textContent = data.people_count !== undefined ? data.people_count : 0;
        if (DOM.metricCarCount) {
            DOM.metricCarCount.textContent = data.car_count !== undefined ? data.car_count : 0;
        }
        if (DOM.metricCarLabel && data.car_count_label) {
            DOM.metricCarLabel.textContent = `🚗 ${data.car_count_label}`;
        }
        if (DOM.zoneModeBadge) {
            DOM.zoneModeBadge.textContent = data.zone_mode || (data.zone_enabled ? "Selected Zone" : "Full View");
            if (data.zone_enabled) {
                DOM.zoneModeBadge.style.background = "#1e3a8a";
                DOM.zoneModeBadge.style.color = "#93c5fd";
            } else {
                DOM.zoneModeBadge.style.background = "#334155";
                DOM.zoneModeBadge.style.color = "#94a3b8";
            }
        }
        if (DOM.zoneToggleCheckbox && document.activeElement !== DOM.zoneToggleCheckbox) {
            DOM.zoneToggleCheckbox.checked = !!data.zone_enabled;
        }
        DOM.metricDetections.textContent = data.detection_count == null ? "?" : data.detection_count;
        DOM.metricTracks.textContent = data.track_count || 0;
        DOM.metricProcessingFps.textContent = Number(data.processing_fps || 0).toFixed(1);
        DOM.metricStreamFps.textContent = Number(data.stream_fps || 0).toFixed(1);
        DOM.metricYoloLatency.textContent = `${Number(data.yolo_latency_ms || 0).toFixed(1)} ms`;
        DOM.metricPipelineLatency.textContent = `${Number(data.pipeline_latency_ms || 0).toFixed(1)} ms`;

        DOM.infoDevice.textContent = data.device || "CPU";
        DOM.infoGpu.textContent = data.gpu_name || "N/A";
        DOM.infoVram.textContent = `${Number(data.vram_mb || 0).toFixed(1)} MB`;
        DOM.infoModel.textContent = `${data.model_name || "YOLO11s"} (${data.input_size || "640x640"})`;

        DOM.infoEventsToday.textContent = data.event_count_today || 0;
        DOM.infoFilteredEvents.textContent = data.filtered_event_count || 0;
        DOM.infoLastSavedCount.textContent = data.last_saved_people_count || 0;
        DOM.infoLastEvent.textContent = data.last_event_time || data.last_event || "None";
    }

    function handleTelemetryError() {
        state.consecutiveErrors++;
        DOM.pingLatency.textContent = "-- ms";
        if (state.consecutiveErrors >= 3) {
            updateStatus("DISCONNECTED", "AI Server connection lost");
        }
    }

    function updateStatus(status, errorMessage) {
        const cleanStatus = (status || "DISCONNECTED").toUpperCase();

        DOM.statusBadge.textContent = `STATUS: ${cleanStatus}`;
        DOM.statusBadge.className = `status-badge status-${cleanStatus.toLowerCase()}`;
        DOM.sidebarConnStatus.textContent = cleanStatus;
        DOM.sidebarConnStatus.className = `badge badge-${cleanStatus.toLowerCase()}`;

        if (cleanStatus === "ERROR") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-error";
            const isAuth = (errorMessage || "").includes("AUTH/ANTI_BOT") || (errorMessage || "").toLowerCase().includes("not a bot");
            if (isAuth) {
                DOM.alertBanner.innerHTML = `⛔ <strong>Lỗi AUTH/ANTI_BOT:</strong> YouTube yêu cầu xác minh bot ("Sign in to confirm you're not a bot"). Đã dừng kết nối.`;
            } else {
                DOM.alertBanner.innerHTML = `⚠️ <strong>Camera Status: ERROR</strong> — ${errorMessage || "Stream ended or camera disconnected unexpectedly."}`;
            }
        } else if (cleanStatus === "VIDEO_FINISHED") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-info";
            DOM.alertBanner.innerHTML = `🏁 <strong>Video đã phát xong (VIDEO_FINISHED).</strong>`;
        } else if (cleanStatus === "WARNING") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `⚠️ <strong>Camera Warning:</strong> ${errorMessage || "Frame delay detected (>5s)..."}`;
        } else if (cleanStatus === "DISCONNECTED") {
            DOM.alertBanner.style.display = "block";
            DOM.alertBanner.className = "alert-banner alert-warning";
            DOM.alertBanner.innerHTML = `📡 <strong>Connecting to AI pipeline...</strong> Ensure <code>python src/main.py</code> is running.`;
        } else {
            DOM.alertBanner.style.display = "none";
        }
    }

    /**
     * Poll Recent Occupancy Events.
     */
    async function pollEvents() {
        try {
            const response = await fetch(apiUrl("/events?limit=5"));
            if (response.ok) {
                const data = await response.json();
                renderEvents(data.events || []);
            }
        } catch (err) {}
    }

    function renderEvents(events) {
        const jsonStr = JSON.stringify(events);
        if (jsonStr === state.lastEventsJson) return;
        state.lastEventsJson = jsonStr;

        if (!events || events.length === 0) {
            DOM.eventsContainer.innerHTML = '<div class="events-empty">No occupancy change events logged yet today.</div>';
            return;
        }

        DOM.eventsContainer.innerHTML = events.slice(0, 5).map(ev => {
            const countDiff = ev.new_count - ev.old_count;
            const diffClass = countDiff > 0 ? "event-badge-increase" : "event-badge-decrease";
            const diffSign = countDiff > 0 ? `+${countDiff}` : `${countDiff}`;
            const timeStr = formatEventTime(ev.timestamp);
            const snapshotUrl = ev.snapshot_path
                ? apiUrl(`/event_snapshot?path=${encodeURIComponent(ev.snapshot_path)}`)
                : (ev.id ? apiUrl(`/event_snapshot?id=${encodeURIComponent(ev.id)}`) : "");

            return `
                <div class="event-card">
                    <div class="event-thumb-wrapper">
                        ${snapshotUrl
                            ? `<img class="event-thumb" src="${snapshotUrl}" alt="Event ${ev.id}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=\\'event-thumb-placeholder\\'>📷 No Image</div>';">`
                            : `<div class="event-thumb-placeholder">📷 No Image</div>`}
                    </div>
                    <div class="event-details">
                        <div class="event-top-row">
                            <span class="event-badge ${diffClass}">${diffSign} People</span>
                            <span class="event-time">${timeStr}</span>
                        </div>
                        <div class="event-count-flow">
                            <span class="count-old">${ev.old_count}</span>
                            <span class="count-arrow">→</span>
                            <span class="count-new">${ev.new_count}</span>
                        </div>
                        <div class="event-meta">
                            <span>ID: #${ev.id}</span>
                            <span>Cam: ${escapeHtml(ev.camera_id || "cam")}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join("");
    }

    function formatEventTime(timestamp) {
        if (!timestamp) return "Just now";
        try {
            const date = new Date(timestamp * 1000);
            return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        } catch (e) {
            return "Just now";
        }
    }

    /**
     * Target Registration & Management (Target Person Flow).
     */
    async function loadTargets() {
        try {
            const resp = await fetch(apiUrl("/api/targets"));
            if (resp.ok) {
                const data = await resp.json();
                renderTargets(data.targets || []);
            }
        } catch (e) {
            console.warn("Failed to load targets:", e);
        }
    }

    function renderTargets(targets) {
        if (DOM.targetCount) {
            DOM.targetCount.textContent = targets.length;
        }
        if (!DOM.targetsList) return;
        if (targets.length === 0) {
            DOM.targetsList.innerHTML = '<div class="target-item-empty">Chưa có người nào được đăng ký. Bấm "+ Add Person" để đăng ký đối tượng tìm kiếm.</div>';
            return;
        }

        DOM.targetsList.innerHTML = targets.map(t => {
            const isSelected = t.is_selected !== false;
            const activeClass = isSelected ? "active-target" : "inactive-target";
            const checkIcon = isSelected ? "✓" : "○";
            const colorBadge = t.clothing_color ? `<span class="target-badge badge-color">${escapeHtml(t.clothing_color)}</span>` : "";
            const faceBadge = (t.has_face || t.has_face_feature) ? `<span class="target-badge badge-face">ArcFace 512D</span>` : "";
            const thumbUrl = t.source_image_path ? apiUrl(`/api/targets/${encodeURIComponent(t.id)}/image`) : "";
            const thumbHtml = thumbUrl
                ? `<img class="target-thumb" src="${thumbUrl}" alt="${escapeHtml(t.name)}" onerror="this.outerHTML='<span class=\\'target-avatar-icon\\'>👤</span>';">`
                : `<span class="target-avatar-icon">👤</span>`;

            return `
                <div class="target-item ${activeClass}" onclick="window.dattToggleTargetSelection('${escapeHtml(t.id)}', ${!isSelected})">
                    <div class="target-thumb-wrap">
                        ${thumbHtml}
                    </div>
                    <div class="target-info">
                        <span class="target-name">${escapeHtml(t.name)}</span>
                        <div class="target-badges">
                            ${faceBadge}${colorBadge}
                            <span class="target-status-pill ${isSelected ? 'pill-selected' : 'pill-deselected'}">
                                ${isSelected ? 'Đang tìm kiếm' : 'Tạm bỏ qua'}
                            </span>
                        </div>
                    </div>
                    <div class="target-actions-wrap" onclick="event.stopPropagation();">
                        <button type="button" class="target-toggle-btn ${isSelected ? 'selected' : ''}" title="${isSelected ? 'Bỏ chọn' : 'Chọn tìm'}" onclick="window.dattToggleTargetSelection('${escapeHtml(t.id)}', ${!isSelected})">
                            ${checkIcon}
                        </button>
                        <button type="button" class="target-del-btn" title="Xóa Target" onclick="window.dattDeleteTarget('${escapeHtml(t.id)}')">✖</button>
                    </div>
                </div>
            `;
        }).join("");
    }

    window.dattToggleTargetSelection = async function(targetId, selectState) {
        try {
            const resp = await fetch(apiUrl(`/api/targets/${encodeURIComponent(targetId)}/select`), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ selected: selectState })
            });
            if (resp.ok) {
                await loadTargets();
            }
        } catch (e) {
            console.warn("Failed to toggle target selection:", e);
        }
    };

    window.dattDeleteTarget = async function(targetId) {
        if (!confirm("Bạn có chắc chắn muốn xóa đối tượng này?")) return;
        try {
            const resp = await fetch(apiUrl(`/api/targets/${encodeURIComponent(targetId)}`), {
                method: "DELETE"
            });
            if (resp.ok) {
                await loadTargets();
            }
        } catch (err) {}
    };

    function initAddPersonModal() {
        if (DOM.btnOpenAddPersonModal && DOM.addPersonModal) {
            DOM.btnOpenAddPersonModal.addEventListener("click", () => {
                DOM.addPersonModal.style.display = "flex";
                if (DOM.addPersonFeedback) DOM.addPersonFeedback.textContent = "";
                if (DOM.targetFacePreviewContainer) DOM.targetFacePreviewContainer.style.display = "none";
                if (DOM.targetFaceFilename) DOM.targetFaceFilename.textContent = "Chọn hoặc kéo thả ảnh chân dung (JPG, PNG)";
                if (DOM.targetNameInput) DOM.targetNameInput.value = "";
                if (DOM.targetFaceInput) DOM.targetFaceInput.value = "";
            });
        }

        const closeAddPerson = () => {
            if (DOM.addPersonModal) DOM.addPersonModal.style.display = "none";
        };

        if (DOM.btnCloseAddPersonModal) DOM.btnCloseAddPersonModal.addEventListener("click", closeAddPerson);
        if (DOM.btnCancelAddPersonModal) DOM.btnCancelAddPersonModal.addEventListener("click", closeAddPerson);

        if (DOM.targetFaceInput) {
            DOM.targetFaceInput.addEventListener("change", (e) => {
                const file = e.target.files[0];
                if (file) {
                    if (DOM.targetFaceFilename) DOM.targetFaceFilename.textContent = file.name;
                    const reader = new FileReader();
                    reader.onload = (loadEvt) => {
                        if (DOM.targetFacePreview) DOM.targetFacePreview.src = loadEvt.target.result;
                        if (DOM.targetFacePreviewContainer) DOM.targetFacePreviewContainer.style.display = "block";
                    };
                    reader.readAsDataURL(file);
                } else {
                    if (DOM.targetFaceFilename) DOM.targetFaceFilename.textContent = "Chọn hoặc kéo thả ảnh chân dung (JPG, PNG)";
                    if (DOM.targetFacePreviewContainer) DOM.targetFacePreviewContainer.style.display = "none";
                }
            });
        }
    }

    async function registerTarget() {
        const name = DOM.targetNameInput ? DOM.targetNameInput.value.trim() : "";
        const color = DOM.targetColorSelect ? DOM.targetColorSelect.value : "";
        const threshold = DOM.targetThresholdInput ? DOM.targetThresholdInput.value : "0.45";
        const file = DOM.targetFaceInput ? DOM.targetFaceInput.files[0] : null;

        const feedbackEl = DOM.addPersonFeedback || DOM.targetFeedback;

        if (!name) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = "Họ và tên / Mã nhận dạng là bắt buộc.";
            }
            return;
        }

        const formData = new FormData();
        formData.append("name", name);
        if (color) formData.append("color", color);
        if (threshold) formData.append("threshold", threshold);
        if (file) formData.append("face_image", file);

        if (DOM.registerTargetBtn) DOM.registerTargetBtn.disabled = true;
        if (feedbackEl) {
            feedbackEl.className = "feedback-msg";
            feedbackEl.textContent = "Đang trích xuất đặc trưng khuôn mặt (SCRFD + ArcFace 512D)...";
        }

        try {
            const resp = await fetch(apiUrl("/api/register_target"), {
                method: "POST",
                body: formData
            });
            const data = await resp.json();
            if (resp.ok && data.status === "ok") {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg success";
                    feedbackEl.textContent = `Đăng ký thành công: ${data.target.name}`;
                }
                await loadTargets();

                setTimeout(() => {
                    if (DOM.addPersonModal) DOM.addPersonModal.style.display = "none";
                    if (DOM.targetNameInput) DOM.targetNameInput.value = "";
                    if (DOM.targetFaceInput) DOM.targetFaceInput.value = "";
                    if (DOM.targetFacePreviewContainer) DOM.targetFacePreviewContainer.style.display = "none";
                }, 500);
            } else {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg error";
                    feedbackEl.textContent = data.message || "Đăng ký đối tượng thất bại.";
                }
            }
        } catch (err) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = `Lỗi mạng: ${err.message}`;
            }
        } finally {
            if (DOM.registerTargetBtn) DOM.registerTargetBtn.disabled = false;
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /* ==============================================================================
     * UNIFIED WATCHLIST MODULE & NAVIGATION CONTROLLER
     * ============================================================================== */

    const watchlistState = {
        activeTab: "face",
        faces: [],
        vehicles: [],
        faceDetectionsMap: {},
        faceFilter: {
            search: "",
            status: "all",
            sort: "newest"
        },
        vehicleFilter: {
            search: "",
            type: "all",
            status: "all"
        },
        selectedFaceTarget: null,
        selectedVehicle: null,
        deleteTarget: null,
        newFaceFile: null
    };

    /**
     * Update active navigation button highlights across all screens.
     */
    function updateActiveNavHighlight(activeNav) {
        document.querySelectorAll("[data-nav]").forEach(btn => {
            if (btn.getAttribute("data-nav") === activeNav) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    /**
     * Global Navigation Dispatcher.
     */
    function navigateTo(navKey) {
        if (navKey === "watchlist") {
            const url = new URL(window.location);
            url.pathname = "/watchlist";
            if (watchlistState.activeTab) {
                url.searchParams.set("type", watchlistState.activeTab);
            }
            history.pushState(null, "", url.toString());
            setUiState(UI_STATE.WATCHLIST);
        } else if (navKey === "camera") {
            const url = new URL(window.location);
            url.pathname = "/cameras";
            history.pushState(null, "", url.toString());
            setUiState(UI_STATE.CAMERA_MANAGEMENT);
        } else if (navKey === "dashboard" || navKey === "live") {
            history.pushState(null, "", "/");
            if (state.activeCameraName) {
                setUiState(UI_STATE.MONITORING, {
                    name: state.activeCameraName,
                    provider: state.activeProvider,
                    source_type: state.activeSourceType
                });
            } else {
                checkInitialAppState();
            }
        } else if (navKey === "events") {
            const url = new URL(window.location);
            url.pathname = "/events";
            history.pushState(null, "", url.toString());
            setUiState(UI_STATE.EVENT_CENTER);
        } else if (navKey === "alerts") {
            showWatchlistBanner("Hệ thống Cảnh báo (Alerts Engine): Đang theo dõi các sự kiện thời gian thực.", "warning");
        } else if (navKey === "analytics") {
            showWatchlistBanner("Phân tích Thống kê (Analytics): Đang tổng hợp số liệu phát hiện.", "info");
        } else if (navKey === "settings") {
            showWatchlistBanner("Cài đặt Hệ thống (Settings): Cấu hình tham số nhận diện và ngưỡng so khớp.", "info");
        }
    }

    /**
     * Switch Watchlist Tab (Face vs Vehicle).
     */
    function switchWatchlistTab(tabName, updateUrl = true) {
        watchlistState.activeTab = tabName;
        if (tabName === "vehicle") {
            if (DOM.tabBtnWatchlistFace) DOM.tabBtnWatchlistFace.classList.remove("active");
            if (DOM.tabBtnWatchlistVehicle) DOM.tabBtnWatchlistVehicle.classList.add("active");
            if (DOM.paneFaceWatchlist) DOM.paneFaceWatchlist.style.display = "none";
            if (DOM.paneVehicleWatchlist) DOM.paneVehicleWatchlist.style.display = "flex";
        } else {
            if (DOM.tabBtnWatchlistFace) DOM.tabBtnWatchlistFace.classList.add("active");
            if (DOM.tabBtnWatchlistVehicle) DOM.tabBtnWatchlistVehicle.classList.remove("active");
            if (DOM.paneFaceWatchlist) DOM.paneFaceWatchlist.style.display = "flex";
            if (DOM.paneVehicleWatchlist) DOM.paneVehicleWatchlist.style.display = "none";
        }

        if (updateUrl && window.location.pathname === "/watchlist") {
            const url = new URL(window.location);
            url.searchParams.set("type", tabName);
            history.replaceState(null, "", url.toString());
        }
    }

    /**
     * Banner Notification for Watchlist.
     */
    function showWatchlistBanner(msg, type = "info") {
        if (!DOM.watchlistBanner) return;
        DOM.watchlistBanner.className = `alert-banner alert-${type}`;
        DOM.watchlistBanner.textContent = msg;
        DOM.watchlistBanner.style.display = "block";
        setTimeout(() => {
            if (DOM.watchlistBanner) DOM.watchlistBanner.style.display = "none";
        }, 5000);
    }

    /**
     * Load Full Watchlist Data (Faces & Vehicles).
     */
    async function loadWatchlist() {
        if (DOM.faceTableSkeleton) DOM.faceTableSkeleton.style.display = "flex";
        if (DOM.vehicleTableSkeleton) DOM.vehicleTableSkeleton.style.display = "flex";
        if (DOM.faceTableWrapper) DOM.faceTableWrapper.style.display = "none";
        if (DOM.vehicleTableWrapper) DOM.vehicleTableWrapper.style.display = "none";
        if (DOM.faceTableError) DOM.faceTableError.style.display = "none";
        if (DOM.vehicleTableError) DOM.vehicleTableError.style.display = "none";
        if (DOM.faceTableEmpty) DOM.faceTableEmpty.style.display = "none";
        if (DOM.vehicleTableEmpty) DOM.vehicleTableEmpty.style.display = "none";

        try {
            // Parallel fetch: Targets, Vehicles, FaceEvents
            const [respFaces, respVehicles, respFaceEvents] = await Promise.allSettled([
                fetch(apiUrl("/api/targets")),
                fetch(apiUrl("/api/watchlist/vehicles")),
                fetch(apiUrl("/api/events/faces?limit=200"))
            ]);

            // 1. Process Faces
            if (respFaces.status === "fulfilled" && respFaces.value.ok) {
                const data = await respFaces.value.json();
                watchlistState.faces = data.targets || [];
                renderTargets(watchlistState.faces); // Update camera dashboard sidebar list
            } else {
                console.warn("[WATCHLIST] Failed to load faces:", respFaces);
            }

            // 2. Process Face Detection Events for statistics
            if (respFaceEvents.status === "fulfilled" && respFaceEvents.value.ok) {
                const evData = await respFaceEvents.value.json();
                const events = evData.events || [];
                const map = {};
                events.forEach(e => {
                    const tid = e.target_id;
                    if (tid) {
                        if (!map[tid]) {
                            map[tid] = { count: 0, lastSeen: e.created_at };
                        }
                        map[tid].count += 1;
                    }
                });
                watchlistState.faceDetectionsMap = map;
            }

            // 3. Process Vehicles
            if (respVehicles.status === "fulfilled" && respVehicles.value.ok) {
                const vData = await respVehicles.value.json();
                watchlistState.vehicles = vData.vehicles || [];
            } else {
                console.warn("[WATCHLIST] Failed to load vehicles:", respVehicles);
            }

            updateWatchlistStats();
            renderFaceTable();
            renderVehicleTable();
        } catch (err) {
            console.error("[WATCHLIST] Exception loading watchlist:", err);
            if (DOM.faceTableError) {
                DOM.faceTableError.style.display = "flex";
                if (DOM.faceTableErrorMsg) DOM.faceTableErrorMsg.textContent = String(err.message || err);
            }
            if (DOM.vehicleTableError) {
                DOM.vehicleTableError.style.display = "flex";
                if (DOM.vehicleTableErrorMsg) DOM.vehicleTableErrorMsg.textContent = String(err.message || err);
            }
        } finally {
            if (DOM.faceTableSkeleton) DOM.faceTableSkeleton.style.display = "none";
            if (DOM.vehicleTableSkeleton) DOM.vehicleTableSkeleton.style.display = "none";
        }
    }

    /**
     * Update Watchlist Metrics & Badges.
     */
    function updateWatchlistStats() {
        const totalFaces = watchlistState.faces.length;
        const activeFaces = watchlistState.faces.filter(f => f.is_selected !== false).length;
        const totalVehicles = watchlistState.vehicles.length;
        const activeVehicles = watchlistState.vehicles.filter(v => v.status === "active").length;

        // Total detections count
        let totalFaceDetections = 0;
        Object.values(watchlistState.faceDetectionsMap).forEach(v => {
            totalFaceDetections += v.count || 0;
        });

        let totalVehicleDetections = 0;
        watchlistState.vehicles.forEach(v => {
            totalVehicleDetections += v.detection_count || 0;
        });

        // Hero Tab Numbers
        if (DOM.faceHeroTotalCount) DOM.faceHeroTotalCount.textContent = totalFaces;
        if (DOM.vehicleHeroTotalCount) DOM.vehicleHeroTotalCount.textContent = totalVehicles;

        // Navigation Badges
        const totalCount = totalFaces + totalVehicles;
        if (DOM.selectionWatchlistBadge) DOM.selectionWatchlistBadge.textContent = totalCount;
        if (DOM.navWatchlistBadgeDash) DOM.navWatchlistBadgeDash.textContent = totalCount;
        if (DOM.navWatchlistBadgeWl) DOM.navWatchlistBadgeWl.textContent = totalCount;

        // Face Summary Cards
        if (DOM.faceStatTotal) DOM.faceStatTotal.textContent = totalFaces;
        if (DOM.faceStatActive) DOM.faceStatActive.textContent = activeFaces;
        if (DOM.faceStatDetectedToday) DOM.faceStatDetectedToday.textContent = totalFaceDetections > 0 ? totalFaceDetections : "--";

        // Vehicle Summary Cards
        if (DOM.vehicleStatTotal) DOM.vehicleStatTotal.textContent = totalVehicles;
        if (DOM.vehicleStatActive) DOM.vehicleStatActive.textContent = activeVehicles;
        if (DOM.vehicleStatDetectedToday) DOM.vehicleStatDetectedToday.textContent = totalVehicleDetections > 0 ? totalVehicleDetections : "--";
    }

    /**
     * Render Face Watchlist Table.
     */
    function renderFaceTable() {
        if (!DOM.faceTableBody) return;

        let filtered = [...watchlistState.faces];
        const search = (watchlistState.faceFilter.search || "").toLowerCase().trim();
        const status = watchlistState.faceFilter.status;
        const sort = watchlistState.faceFilter.sort;

        // Filter search
        if (search) {
            filtered = filtered.filter(f => {
                const nameMatch = (f.name || "").toLowerCase().includes(search);
                const idMatch = (f.id || "").toLowerCase().includes(search);
                const colorMatch = (f.clothing_color || "").toLowerCase().includes(search);
                return nameMatch || idMatch || colorMatch;
            });
        }

        // Filter status
        if (status === "active") {
            filtered = filtered.filter(f => f.is_selected !== false);
        } else if (status === "inactive") {
            filtered = filtered.filter(f => f.is_selected === false);
        }

        // Sort
        if (sort === "name_asc") {
            filtered.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
        } else if (sort === "name_desc") {
            filtered.sort((a, b) => (b.name || "").localeCompare(a.name || ""));
        } else if (sort === "detected") {
            filtered.sort((a, b) => {
                const cntA = (watchlistState.faceDetectionsMap[a.id] || {}).count || 0;
                const cntB = (watchlistState.faceDetectionsMap[b.id] || {}).count || 0;
                return cntB - cntA;
            });
        } else if (sort === "oldest") {
            filtered.sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
        } else {
            // newest
            filtered.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
        }

        if (filtered.length === 0) {
            if (DOM.faceTableWrapper) DOM.faceTableWrapper.style.display = "none";
            if (DOM.faceTableEmpty) DOM.faceTableEmpty.style.display = "flex";
            return;
        }

        if (DOM.faceTableEmpty) DOM.faceTableEmpty.style.display = "none";
        if (DOM.faceTableWrapper) DOM.faceTableWrapper.style.display = "block";

        DOM.faceTableBody.innerHTML = filtered.map(t => {
            const isSelected = t.is_selected !== false;
            const statusClass = isSelected ? "status-active" : "status-disabled";
            const statusText = isSelected ? "Active" : "Disabled";
            const thumbUrl = t.source_image_path ? apiUrl(`/api/targets/${encodeURIComponent(t.id)}/image`) : "";
            const thumbHtml = thumbUrl
                ? `<img class="table-avatar-img" src="${thumbUrl}" alt="${escapeHtml(t.name)}" onerror="this.outerHTML='<span class=\\'table-avatar-fallback\\'>👤</span>';">`
                : `<span class="table-avatar-fallback">👤</span>`;

            const statInfo = watchlistState.faceDetectionsMap[t.id] || { count: 0, lastSeen: null };
            const detectedCount = statInfo.count || 0;
            const lastSeenStr = statInfo.lastSeen ? formatDateTime(statInfo.lastSeen) : "--";
            const createdStr = t.created_at ? formatDateTime(t.created_at) : "--";
            const shortId = t.id ? (t.id.length > 8 ? t.id.substring(0, 8) + "..." : t.id) : "--";

            return `
                <tr onclick="window.dattOpenFaceDrawer('${escapeHtml(t.id)}')">
                    <td>
                        <div class="table-avatar-wrap">
                            ${thumbHtml}
                        </div>
                    </td>
                    <td>
                        <span class="table-target-name">${escapeHtml(t.name)}</span>
                        ${t.clothing_color ? `<span class="table-target-sub">Màu áo: ${escapeHtml(t.clothing_color)}</span>` : ""}
                    </td>
                    <td>
                        <span class="target-id-pill" title="${escapeHtml(t.id)}">${escapeHtml(shortId)}</span>
                    </td>
                    <td>
                        <span class="status-pill ${statusClass}">${statusText}</span>
                    </td>
                    <td>
                        <span class="count-badge-table ${detectedCount > 0 ? '' : 'count-badge-zero'}">${detectedCount}</span>
                    </td>
                    <td>
                        <span class="font-mono" style="font-size: 0.78rem;">${escapeHtml(lastSeenStr)}</span>
                    </td>
                    <td>
                        <span style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(createdStr)}</span>
                    </td>
                    <td onclick="event.stopPropagation();">
                        <div class="table-actions-cell">
                            <button type="button" class="row-action-btn" title="Xem chi tiết" onclick="window.dattOpenFaceDrawer('${escapeHtml(t.id)}')">
                                👁️
                            </button>
                            <button type="button" class="row-action-btn" title="${isSelected ? 'Tạm ngưng' : 'Kích hoạt'}" onclick="window.dattToggleFaceActive('${escapeHtml(t.id)}', ${!isSelected})">
                                ${isSelected ? '⏸️' : '▶️'}
                            </button>
                            <button type="button" class="row-action-btn btn-delete" title="Xóa đối tượng" onclick="window.dattConfirmDelete('face', '${escapeHtml(t.id)}', '${escapeHtml(t.name)}')">
                                🗑️
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    /**
     * Render Vehicle Watchlist Table.
     */
    function renderVehicleTable() {
        if (!DOM.vehicleTableBody) return;

        let filtered = [...watchlistState.vehicles];
        const search = (watchlistState.vehicleFilter.search || "").toLowerCase().trim();
        const typeFilter = watchlistState.vehicleFilter.type;
        const statusFilter = watchlistState.vehicleFilter.status;

        // Search
        if (search) {
            filtered = filtered.filter(v => {
                const plateMatch = (v.plate_number || "").toLowerCase().includes(search);
                const normMatch = (v.normalized_plate || "").toLowerCase().includes(search);
                const nameMatch = (v.name || "").toLowerCase().includes(search);
                const ownerMatch = (v.owner_info || "").toLowerCase().includes(search);
                return plateMatch || normMatch || nameMatch || ownerMatch;
            });
        }

        // Type
        if (typeFilter && typeFilter !== "all") {
            filtered = filtered.filter(v => (v.vehicle_type || "car") === typeFilter);
        }

        // Status
        if (statusFilter && statusFilter !== "all") {
            filtered = filtered.filter(v => (v.status || "active") === statusFilter);
        }

        if (filtered.length === 0) {
            if (DOM.vehicleTableWrapper) DOM.vehicleTableWrapper.style.display = "none";
            if (DOM.vehicleTableEmpty) DOM.vehicleTableEmpty.style.display = "flex";
            return;
        }

        if (DOM.vehicleTableEmpty) DOM.vehicleTableEmpty.style.display = "none";
        if (DOM.vehicleTableWrapper) DOM.vehicleTableWrapper.style.display = "block";

        DOM.vehicleTableBody.innerHTML = filtered.map(v => {
            const isActive = (v.status || "active") === "active";
            const statusClass = isActive ? "status-active" : "status-disabled";
            const statusText = isActive ? "Active" : "Disabled";
            const detectedCount = v.detection_count || 0;
            const lastSeenStr = v.last_seen ? formatDateTime(v.last_seen) : "--";
            const createdStr = v.created_at ? formatDateTime(v.created_at) : "--";
            const typeLabel = getVehicleTypeLabel(v.vehicle_type);

            return `
                <tr onclick="window.dattOpenVehicleDrawer('${escapeHtml(v.id)}')">
                    <td>
                        <span class="license-plate-badge-table">${escapeHtml(v.plate_number)}</span>
                    </td>
                    <td>
                        <span class="vehicle-type-tag">${typeLabel}</span>
                    </td>
                    <td>
                        <span class="table-target-name">${escapeHtml(v.name || "--")}</span>
                        ${v.notes ? `<span class="table-target-sub">${escapeHtml(v.notes)}</span>` : ""}
                    </td>
                    <td>
                        <span style="font-size: 0.82rem; color: var(--text-primary); font-weight: 500;">${escapeHtml(v.owner_info || "--")}</span>
                    </td>
                    <td>
                        <span class="status-pill ${statusClass}">${statusText}</span>
                    </td>
                    <td>
                        <span class="count-badge-table ${detectedCount > 0 ? '' : 'count-badge-zero'}">${detectedCount}</span>
                    </td>
                    <td>
                        <span class="font-mono" style="font-size: 0.78rem;">${escapeHtml(lastSeenStr)}</span>
                    </td>
                    <td>
                        <span style="font-size: 0.78rem; color: var(--text-muted);">${escapeHtml(createdStr)}</span>
                    </td>
                    <td onclick="event.stopPropagation();">
                        <div class="table-actions-cell">
                            <button type="button" class="row-action-btn" title="Xem chi tiết" onclick="window.dattOpenVehicleDrawer('${escapeHtml(v.id)}')">
                                👁️
                            </button>
                            <button type="button" class="row-action-btn" title="Chỉnh sửa" onclick="window.dattOpenEditVehicleModal('${escapeHtml(v.id)}')">
                                ✏️
                            </button>
                            <button type="button" class="row-action-btn" title="${isActive ? 'Tạm ngưng' : 'Kích hoạt'}" onclick="window.dattToggleVehicleActive('${escapeHtml(v.id)}', '${isActive ? 'disabled' : 'active'}')">
                                ${isActive ? '⏸️' : '▶️'}
                            </button>
                            <button type="button" class="row-action-btn btn-delete" title="Xóa phương tiện" onclick="window.dattConfirmDelete('vehicle', '${escapeHtml(v.id)}', '${escapeHtml(v.plate_number)}')">
                                🗑️
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    /**
     * Vehicle Type Helper.
     */
    function getVehicleTypeLabel(type) {
        switch (type) {
            case "car": return "🚗 Ô tô";
            case "motorbike": return "🏍️ Xe máy";
            case "truck": return "🚚 Xe tải";
            case "bus": return "🚌 Xe buýt";
            case "container": return "📦 Container";
            default: return "🚗 Phương tiện";
        }
    }

    /**
     * Date/Time Formatter Helper.
     */
    function formatDateTime(isoString) {
        if (!isoString) return "--";
        try {
            const d = new Date(isoString);
            if (isNaN(d.getTime())) return isoString;
            const pad = (n) => String(n).padStart(2, "0");
            const day = pad(d.getDate());
            const month = pad(d.getMonth() + 1);
            const year = d.getFullYear();
            const hours = pad(d.getHours());
            const mins = pad(d.getMinutes());
            const secs = pad(d.getSeconds());
            return `${day}/${month}/${year} ${hours}:${mins}:${secs}`;
        } catch (e) {
            return isoString;
        }
    }

    /**
     * Open Face Detail Drawer.
     */
    window.dattOpenFaceDrawer = async function (targetId) {
        if (!watchlistState.faces || watchlistState.faces.length === 0) {
            await loadWatchlist("face");
        }
        const target = (targetId ? watchlistState.faces.find(f => f.id === targetId) : null) || watchlistState.faces[0];
        if (!target) return;

        watchlistState.selectedFaceTarget = target;
        closeAllDrawers();

        if (DOM.faceDrawerName) DOM.faceDrawerName.textContent = target.name;
        if (DOM.faceDrawerId) DOM.faceDrawerId.textContent = target.id;
        const isSelected = target.is_selected !== false;
        if (DOM.faceDrawerStatus) {
            DOM.faceDrawerStatus.className = `status-pill ${isSelected ? 'status-active' : 'status-disabled'}`;
            DOM.faceDrawerStatus.textContent = isSelected ? "Active" : "Disabled";
        }
        if (DOM.faceToggleBtnText) {
            DOM.faceToggleBtnText.textContent = isSelected ? "Tạm ngưng" : "Kích hoạt";
        }
        if (DOM.faceDrawerCreatedAt) DOM.faceDrawerCreatedAt.textContent = formatDateTime(target.created_at);
        if (DOM.faceDrawerThreshold) DOM.faceDrawerThreshold.textContent = target.face_threshold || "0.45";
        if (DOM.faceDrawerColor) DOM.faceDrawerColor.textContent = target.clothing_color || "Bất kỳ";

        // Portrait
        if (DOM.faceDrawerAvatar) {
            if (target.source_image_path) {
                DOM.faceDrawerAvatar.src = apiUrl(`/api/targets/${encodeURIComponent(target.id)}/image`);
                DOM.faceDrawerAvatar.style.display = "block";
            } else {
                DOM.faceDrawerAvatar.src = "";
                DOM.faceDrawerAvatar.style.display = "none";
            }
        }

        // Stats
        const statInfo = watchlistState.faceDetectionsMap[target.id] || { count: 0, lastSeen: null };
        if (DOM.faceDrawerDetectionCount) DOM.faceDrawerDetectionCount.textContent = statInfo.count || 0;
        if (DOM.faceDrawerLastSeen) DOM.faceDrawerLastSeen.textContent = statInfo.lastSeen ? formatDateTime(statInfo.lastSeen) : "--";

        // Open Drawer UI
        if (DOM.drawerBackdrop) DOM.drawerBackdrop.style.display = "block";
        if (DOM.drawerFaceDetail) DOM.drawerFaceDetail.classList.add("open");

        // Load History
        await loadFaceDetectionHistory(target.id);
    };

    /**
     * Load Face Detection History Timeline.
     */
    async function loadFaceDetectionHistory(targetId) {
        if (!DOM.faceDrawerHistoryList) return;
        if (DOM.faceDrawerHistoryLoading) DOM.faceDrawerHistoryLoading.style.display = "flex";
        if (DOM.faceDrawerHistoryEmpty) DOM.faceDrawerHistoryEmpty.style.display = "none";
        DOM.faceDrawerHistoryList.innerHTML = "";

        try {
            const resp = await fetch(apiUrl(`/api/events/faces?target_id=${encodeURIComponent(targetId)}&limit=25`));
            if (resp.ok) {
                const data = await resp.json();
                const events = data.events || [];
                if (DOM.faceDrawerHistoryBadge) DOM.faceDrawerHistoryBadge.textContent = `${events.length} sự kiện`;

                if (events.length === 0) {
                    if (DOM.faceDrawerHistoryEmpty) DOM.faceDrawerHistoryEmpty.style.display = "block";
                } else {
                    DOM.faceDrawerHistoryList.innerHTML = events.map(ev => {
                        const cropUrl = ev.face_crop_path ? apiUrl(`/api/event_snapshot?path=${encodeURIComponent(ev.face_crop_path)}`) : "";
                        const cropHtml = cropUrl
                            ? `<img class="history-crop-img" src="${cropUrl}" alt="Face Crop" onerror="this.outerHTML='<span class=\\'history-crop-fallback\\'>👤</span>';">`
                            : `<span class="history-crop-fallback">👤</span>`;
                        const simPct = ev.similarity ? (ev.similarity * 100).toFixed(1) + "%" : "MATCH";
                        const timeStr = formatDateTime(ev.created_at);

                        return `
                            <div class="history-card-item">
                                <div class="history-crop-wrap">${cropHtml}</div>
                                <div class="history-card-body">
                                    <div class="history-card-cam">📹 ${escapeHtml(ev.camera_id || 'Unknown camera')}</div>
                                    <div class="history-card-time">${escapeHtml(timeStr)}</div>
                                    <div class="history-card-badges">
                                        <span class="badge-similarity">Similarity: ${escapeHtml(simPct)}</span>
                                        <span class="badge-decision">${escapeHtml(ev.decision || 'MATCH')}</span>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join("");
                }
            } else {
                if (DOM.faceDrawerHistoryEmpty) DOM.faceDrawerHistoryEmpty.style.display = "block";
            }
        } catch (e) {
            console.warn("Failed loading face history:", e);
            if (DOM.faceDrawerHistoryEmpty) DOM.faceDrawerHistoryEmpty.style.display = "block";
        } finally {
            if (DOM.faceDrawerHistoryLoading) DOM.faceDrawerHistoryLoading.style.display = "none";
        }
    }

    /**
     * Open Vehicle Detail Drawer.
     */
    window.dattOpenVehicleDrawer = async function (vehicleId) {
        if (!watchlistState.vehicles || watchlistState.vehicles.length === 0) {
            await loadWatchlist("vehicle");
        }
        const vehicle = (vehicleId ? watchlistState.vehicles.find(v => v.id === vehicleId) : null) || watchlistState.vehicles[0];
        if (!vehicle) return;

        watchlistState.selectedVehicle = vehicle;
        closeAllDrawers();

        if (DOM.vehicleDrawerPlateBadge) DOM.vehicleDrawerPlateBadge.textContent = vehicle.plate_number;
        const isActive = (vehicle.status || "active") === "active";
        if (DOM.vehicleDrawerStatus) {
            DOM.vehicleDrawerStatus.className = `status-pill ${isActive ? 'status-active' : 'status-disabled'}`;
            DOM.vehicleDrawerStatus.textContent = isActive ? "Active" : "Disabled";
        }
        if (DOM.vehicleToggleBtnText) {
            DOM.vehicleToggleBtnText.textContent = isActive ? "Tạm ngưng" : "Kích hoạt";
        }
        if (DOM.vehicleDrawerType) DOM.vehicleDrawerType.textContent = getVehicleTypeLabel(vehicle.vehicle_type);
        if (DOM.vehicleDrawerName) DOM.vehicleDrawerName.textContent = vehicle.name || "--";
        if (DOM.vehicleDrawerOwner) DOM.vehicleDrawerOwner.textContent = vehicle.owner_info || "--";
        if (DOM.vehicleDrawerNotes) DOM.vehicleDrawerNotes.textContent = vehicle.notes || "--";
        if (DOM.vehicleDrawerCreatedAt) DOM.vehicleDrawerCreatedAt.textContent = formatDateTime(vehicle.created_at);

        if (DOM.vehicleDrawerDetectionCount) DOM.vehicleDrawerDetectionCount.textContent = vehicle.detection_count || 0;
        if (DOM.vehicleDrawerLastSeen) DOM.vehicleDrawerLastSeen.textContent = vehicle.last_seen ? formatDateTime(vehicle.last_seen) : "--";

        // Open UI
        if (DOM.drawerBackdrop) DOM.drawerBackdrop.style.display = "block";
        if (DOM.drawerVehicleDetail) DOM.drawerVehicleDetail.classList.add("open");

        // Load History
        await loadVehicleDetectionHistory(vehicle.id);
    };

    /**
     * Load Vehicle Detection History Timeline.
     */
    async function loadVehicleDetectionHistory(vehicleId) {
        if (!DOM.vehicleDrawerHistoryList) return;
        if (DOM.vehicleDrawerHistoryLoading) DOM.vehicleDrawerHistoryLoading.style.display = "flex";
        if (DOM.vehicleDrawerHistoryEmpty) DOM.vehicleDrawerHistoryEmpty.style.display = "none";
        DOM.vehicleDrawerHistoryList.innerHTML = "";

        try {
            const resp = await fetch(apiUrl(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}/detections`));
            if (resp.ok) {
                const data = await resp.json();
                const detections = data.detections || [];
                if (DOM.vehicleDrawerHistoryBadge) DOM.vehicleDrawerHistoryBadge.textContent = `${detections.length} sự kiện`;

                if (detections.length === 0) {
                    if (DOM.vehicleDrawerHistoryEmpty) DOM.vehicleDrawerHistoryEmpty.style.display = "block";
                } else {
                    DOM.vehicleDrawerHistoryList.innerHTML = detections.map(d => {
                        const cropUrl = d.plate_crop_path ? apiUrl(`/api/event_snapshot?path=${encodeURIComponent(d.plate_crop_path)}`) : "";
                        const cropHtml = cropUrl
                            ? `<img class="history-crop-img" src="${cropUrl}" alt="Plate Crop" onerror="this.outerHTML='<span class=\\'history-crop-fallback\\'>🚗</span>';">`
                            : `<span class="history-crop-fallback">🚗</span>`;
                        const confPct = d.confidence ? (d.confidence * 100).toFixed(0) + "%" : "94%";
                        const timeStr = formatDateTime(d.created_at);

                        return `
                            <div class="history-card-item">
                                <div class="history-crop-wrap">${cropHtml}</div>
                                <div class="history-card-body">
                                    <div class="history-card-cam">📹 ${escapeHtml(d.camera_id || 'Camera 01')}</div>
                                    <div class="history-card-time">${escapeHtml(timeStr)}</div>
                                    <div class="history-card-badges">
                                        <span class="license-plate-badge-sm">${escapeHtml(d.plate_text)}</span>
                                        <span class="badge-similarity">Conf: ${escapeHtml(confPct)}</span>
                                    </div>
                                </div>
                            </div>
                        `;
                    }).join("");
                }
            } else {
                if (DOM.vehicleDrawerHistoryEmpty) DOM.vehicleDrawerHistoryEmpty.style.display = "block";
            }
        } catch (e) {
            console.warn("Failed loading vehicle history:", e);
            if (DOM.vehicleDrawerHistoryEmpty) DOM.vehicleDrawerHistoryEmpty.style.display = "block";
        } finally {
            if (DOM.vehicleDrawerHistoryLoading) DOM.vehicleDrawerHistoryLoading.style.display = "none";
        }
    }

    /**
     * Close All Drawers.
     */
    function closeAllDrawers() {
        if (DOM.drawerFaceDetail) DOM.drawerFaceDetail.classList.remove("open");
        if (DOM.drawerVehicleDetail) DOM.drawerVehicleDetail.classList.remove("open");
        if (DOM.drawerBackdrop) DOM.drawerBackdrop.style.display = "none";
    }

    /**
     * Toggle Face Target Active Selection.
     */
    window.dattToggleFaceActive = async function (targetId, selectState) {
        try {
            const resp = await fetch(apiUrl(`/api/targets/${encodeURIComponent(targetId)}/select`), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ selected: selectState })
            });
            if (resp.ok) {
                const target = watchlistState.faces.find(f => f.id === targetId);
                if (target) target.is_selected = selectState;
                updateWatchlistStats();
                renderFaceTable();
                renderTargets(watchlistState.faces);
                if (watchlistState.selectedFaceTarget && watchlistState.selectedFaceTarget.id === targetId) {
                    window.dattOpenFaceDrawer(targetId);
                }
            }
        } catch (e) {
            console.warn("Error toggling face target active state:", e);
        }
    };

    /**
     * Toggle Vehicle Active Status.
     */
    window.dattToggleVehicleActive = async function (vehicleId, newStatus) {
        try {
            const resp = await fetch(apiUrl(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}`), {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            if (resp.ok) {
                const vehicle = watchlistState.vehicles.find(v => v.id === vehicleId);
                if (vehicle) vehicle.status = newStatus;
                updateWatchlistStats();
                renderVehicleTable();
                if (watchlistState.selectedVehicle && watchlistState.selectedVehicle.id === vehicleId) {
                    window.dattOpenVehicleDrawer(vehicleId);
                }
            }
        } catch (e) {
            console.warn("Error toggling vehicle status:", e);
        }
    };

    /**
     * Open Edit Vehicle Watchlist Modal.
     */
    window.dattOpenEditVehicleModal = async function (vehicleId) {
        closeAllDrawers();
        let vehicle = watchlistState.vehicles.find(v => v.id === vehicleId);
        if (!vehicle) {
            try {
                const resp = await fetch(apiUrl(`/api/watchlist/vehicles/${encodeURIComponent(vehicleId)}`));
                if (resp.ok) {
                    const data = await resp.json();
                    vehicle = data.vehicle;
                }
            } catch (e) {}
        }
        if (!vehicle) return;

        if (DOM.inputEditVehicleId) DOM.inputEditVehicleId.value = vehicle.id;
        if (DOM.badgeEditVehiclePlate) DOM.badgeEditVehiclePlate.textContent = vehicle.plate_number;
        if (DOM.selectEditVehicleType) DOM.selectEditVehicleType.value = vehicle.vehicle_type || "car";
        if (DOM.selectEditVehicleStatus) DOM.selectEditVehicleStatus.value = vehicle.status || "active";
        if (DOM.inputEditVehicleName) DOM.inputEditVehicleName.value = vehicle.name || vehicle.display_name || "";
        if (DOM.inputEditVehicleOwner) DOM.inputEditVehicleOwner.value = vehicle.owner_info || "";
        if (DOM.inputEditVehicleNotes) DOM.inputEditVehicleNotes.value = vehicle.notes || "";
        if (DOM.editVehicleFeedback) DOM.editVehicleFeedback.textContent = "";

        if (DOM.modalEditVehicleWatchlist) DOM.modalEditVehicleWatchlist.style.display = "flex";
    };

    /**
     * Submit Vehicle Watchlist Edits.
     */
    async function submitEditVehicleWatchlist() {
        const id = DOM.inputEditVehicleId ? DOM.inputEditVehicleId.value : "";
        if (!id) return;

        const payload = {
            vehicle_type: DOM.selectEditVehicleType ? DOM.selectEditVehicleType.value : "car",
            status: DOM.selectEditVehicleStatus ? DOM.selectEditVehicleStatus.value : "active",
            display_name: (DOM.inputEditVehicleName ? DOM.inputEditVehicleName.value : "").trim(),
            owner_info: (DOM.inputEditVehicleOwner ? DOM.inputEditVehicleOwner.value : "").trim(),
            notes: (DOM.inputEditVehicleNotes ? DOM.inputEditVehicleNotes.value : "").trim()
        };

        if (DOM.btnSubmitEditVehicleWatchlist) DOM.btnSubmitEditVehicleWatchlist.disabled = true;
        if (DOM.editVehicleFeedback) {
            DOM.editVehicleFeedback.className = "feedback-msg";
            DOM.editVehicleFeedback.textContent = "Đang lưu thay đổi...";
        }

        try {
            const resp = await fetch(apiUrl(`/api/watchlist/vehicles/${encodeURIComponent(id)}`), {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.message || "Cập nhật phương tiện thất bại.");
            }
            const data = await resp.json();
            const updated = data.vehicle;
            const idx = watchlistState.vehicles.findIndex(v => v.id === id);
            if (idx !== -1 && updated) {
                watchlistState.vehicles[idx] = updated;
            }
            if (DOM.modalEditVehicleWatchlist) DOM.modalEditVehicleWatchlist.style.display = "none";
            showWatchlistBanner(`Đã cập nhật thông tin phương tiện biển số "${(updated && updated.plate_number) || ''}".`, "success");
            updateWatchlistStats();
            renderVehicleTable();
            if (watchlistState.selectedVehicle && watchlistState.selectedVehicle.id === id) {
                window.dattOpenVehicleDrawer(id);
            }
        } catch (err) {
            if (DOM.editVehicleFeedback) {
                DOM.editVehicleFeedback.className = "feedback-msg error";
                DOM.editVehicleFeedback.textContent = err.message;
            }
        } finally {
            if (DOM.btnSubmitEditVehicleWatchlist) DOM.btnSubmitEditVehicleWatchlist.disabled = false;
        }
    }

    /**
     * Confirm Delete Dialog.
     */
    window.dattConfirmDelete = function (type, id, name) {
        watchlistState.deleteTarget = { type, id, name };
        if (DOM.confirmDeleteTargetName) {
            DOM.confirmDeleteTargetName.textContent = name || id;
        }
        if (DOM.confirmDeleteFeedback) {
            DOM.confirmDeleteFeedback.textContent = "";
            DOM.confirmDeleteFeedback.className = "feedback-msg";
        }
        if (DOM.modalConfirmDelete) DOM.modalConfirmDelete.style.display = "flex";
    };

    /**
     * Execute Delete Target or Vehicle.
     */
    async function executeConfirmDelete() {
        if (!watchlistState.deleteTarget) return;
        const { type, id, name } = watchlistState.deleteTarget;
        const feedbackEl = DOM.confirmDeleteFeedback;

        try {
            let resp;
            if (type === "face") {
                resp = await fetch(apiUrl(`/api/targets/${encodeURIComponent(id)}`), { method: "DELETE" });
            } else {
                resp = await fetch(apiUrl(`/api/watchlist/vehicles/${encodeURIComponent(id)}`), { method: "DELETE" });
            }

            if (resp && resp.ok) {
                if (DOM.modalConfirmDelete) DOM.modalConfirmDelete.style.display = "none";
                closeAllDrawers();
                showWatchlistBanner(`Đã xóa thành công: ${name}`, "success");
                await loadWatchlist();
            } else {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg error";
                    feedbackEl.textContent = "Không thể xóa đối tượng. Vui lòng thử lại.";
                }
            }
        } catch (err) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = `Lỗi xóa: ${err.message || err}`;
            }
        }
    }

    /**
     * Face Image Dropzone Handling for Modal.
     */
    function initFaceDropzone() {
        const dropzone = DOM.faceDropzoneNew;
        const fileInput = DOM.faceFileInputNew;
        if (!dropzone || !fileInput) return;

        ["dragenter", "dragover"].forEach(name => {
            dropzone.addEventListener(name, (e) => {
                e.preventDefault();
                dropzone.classList.add("dragover");
            });
        });

        ["dragleave", "drop"].forEach(name => {
            dropzone.addEventListener(name, (e) => {
                e.preventDefault();
                dropzone.classList.remove("dragover");
            });
        });

        dropzone.addEventListener("drop", (e) => {
            const files = e.dataTransfer.files;
            if (files && files.length > 0) {
                handleFaceFileSelect(files[0]);
            }
        });

        if (DOM.btnBrowseFaceNew) {
            DOM.btnBrowseFaceNew.addEventListener("click", () => fileInput.click());
        }

        fileInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleFaceFileSelect(e.target.files[0]);
            }
        });

        if (DOM.btnRemoveFacePreviewNew) {
            DOM.btnRemoveFacePreviewNew.addEventListener("click", () => {
                watchlistState.newFaceFile = null;
                fileInput.value = "";
                if (DOM.facePreviewCardNew) DOM.facePreviewCardNew.style.display = "none";
                if (DOM.faceDropzoneNew) DOM.faceDropzoneNew.style.display = "block";
            });
        }
    }

    function handleFaceFileSelect(file) {
        if (!file) return;
        const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
        if (![".jpg", ".jpeg", ".png", ".webp"].includes(ext)) {
            if (DOM.addFaceFeedbackNew) {
                DOM.addFaceFeedbackNew.className = "feedback-msg error";
                DOM.addFaceFeedbackNew.textContent = "Vui lòng chọn định dạng ảnh JPG, PNG hoặc WEBP.";
            }
            return;
        }

        watchlistState.newFaceFile = file;
        if (DOM.facePreviewNameNew) DOM.facePreviewNameNew.textContent = file.name;
        if (DOM.facePreviewSizeNew) DOM.facePreviewSizeNew.textContent = `${(file.size / 1024).toFixed(1)} KB`;

        const reader = new FileReader();
        reader.onload = (e) => {
            if (DOM.facePreviewImgNew) DOM.facePreviewImgNew.src = e.target.result;
            if (DOM.facePreviewCardNew) DOM.facePreviewCardNew.style.display = "flex";
            if (DOM.faceDropzoneNew) DOM.faceDropzoneNew.style.display = "none";
        };
        reader.readAsDataURL(file);
    }

    /**
     * Submit Add Face Watchlist Form.
     */
    async function submitAddFaceWatchlist() {
        const nameInput = DOM.inputNewFaceName;
        const name = nameInput ? nameInput.value.trim() : "";
        const color = DOM.selectNewFaceColor ? DOM.selectNewFaceColor.value : "";
        const threshold = DOM.inputNewFaceThreshold ? DOM.inputNewFaceThreshold.value : "0.45";
        const file = watchlistState.newFaceFile;
        const feedbackEl = DOM.addFaceFeedbackNew;

        if (!file) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = "Vui lòng tải lên ảnh chân dung khuôn mặt.";
            }
            return;
        }

        if (!name) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = "Họ tên đối tượng là bắt buộc.";
            }
            if (nameInput) nameInput.focus();
            return;
        }

        const formData = new FormData();
        formData.append("name", name);
        if (color) formData.append("color", color);
        if (threshold) formData.append("threshold", threshold);
        formData.append("face_image", file);

        if (DOM.btnSubmitAddFaceWatchlist) DOM.btnSubmitAddFaceWatchlist.disabled = true;
        if (feedbackEl) {
            feedbackEl.className = "feedback-msg";
            feedbackEl.innerHTML = '<span class="ui-spinner-inline"></span> Đang xử lý khuôn mặt (SCRFD + ArcFace 512D)...';
        }

        try {
            const resp = await fetch(apiUrl("/api/register_target"), {
                method: "POST",
                body: formData
            });
            const data = await resp.json();

            if (resp.ok && data.status === "ok") {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg success";
                    feedbackEl.textContent = `Đã thêm đối tượng vào Face Watchlist: ${data.target.name}`;
                }
                await loadWatchlist();
                setTimeout(() => {
                    if (DOM.modalAddFaceWatchlist) DOM.modalAddFaceWatchlist.style.display = "none";
                    resetAddFaceForm();
                }, 800);
            } else {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg error";
                    feedbackEl.textContent = data.message || `Lỗi đăng ký: ${data.code || 'UNKNOWN'}`;
                }
            }
        } catch (err) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = `Lỗi kết nối máy chủ: ${err.message || err}`;
            }
        } finally {
            if (DOM.btnSubmitAddFaceWatchlist) DOM.btnSubmitAddFaceWatchlist.disabled = false;
        }
    }

    function resetAddFaceForm() {
        if (DOM.inputNewFaceName) DOM.inputNewFaceName.value = "";
        if (DOM.inputNewFaceNotes) DOM.inputNewFaceNotes.value = "";
        if (DOM.selectNewFaceColor) DOM.selectNewFaceColor.value = "";
        if (DOM.inputNewFaceThreshold) DOM.inputNewFaceThreshold.value = "0.45";
        if (DOM.addFaceFeedbackNew) {
            DOM.addFaceFeedbackNew.className = "feedback-msg";
            DOM.addFaceFeedbackNew.textContent = "";
        }
        if (DOM.faceFileInputNew) DOM.faceFileInputNew.value = "";
        watchlistState.newFaceFile = null;
        if (DOM.facePreviewCardNew) DOM.facePreviewCardNew.style.display = "none";
        if (DOM.faceDropzoneNew) DOM.faceDropzoneNew.style.display = "block";
    }

    /**
     * Submit Add Vehicle Watchlist Form.
     */
    async function submitAddVehicleWatchlist() {
        const plateInput = DOM.inputNewVehiclePlate;
        const plate = plateInput ? plateInput.value.trim().toUpperCase() : "";
        const vType = DOM.selectNewVehicleType ? DOM.selectNewVehicleType.value : "car";
        const status = DOM.selectNewVehicleStatus ? DOM.selectNewVehicleStatus.value : "active";
        const name = DOM.inputNewVehicleName ? DOM.inputNewVehicleName.value.trim() : "";
        const owner = DOM.inputNewVehicleOwner ? DOM.inputNewVehicleOwner.value.trim() : "";
        const notes = DOM.inputNewVehicleNotes ? DOM.inputNewVehicleNotes.value.trim() : "";
        const feedbackEl = DOM.addVehicleFeedback;

        if (!plate) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = "Biển số xe là bắt buộc.";
            }
            if (plateInput) plateInput.focus();
            return;
        }

        const norm = plate.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
        if (norm.length < 3) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = "Biển số không hợp lệ. Vui lòng nhập tối thiểu 3 ký tự.";
            }
            if (plateInput) plateInput.focus();
            return;
        }

        if (DOM.btnSubmitAddVehicleWatchlist) DOM.btnSubmitAddVehicleWatchlist.disabled = true;
        if (feedbackEl) {
            feedbackEl.className = "feedback-msg";
            feedbackEl.textContent = "Đang lưu phương tiện vào Watchlist...";
        }

        try {
            const resp = await fetch(apiUrl("/api/watchlist/vehicles"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    plate_number: plate,
                    vehicle_type: vType,
                    status: status,
                    name: name,
                    owner_info: owner,
                    notes: notes
                })
            });
            const data = await resp.json();

            if (resp.ok && data.status === "ok") {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg success";
                    feedbackEl.textContent = `Đã thêm phương tiện ${plate} vào Watchlist!`;
                }
                await loadWatchlist();
                setTimeout(() => {
                    if (DOM.modalAddVehicleWatchlist) DOM.modalAddVehicleWatchlist.style.display = "none";
                    resetAddVehicleForm();
                }, 800);
            } else {
                if (feedbackEl) {
                    feedbackEl.className = "feedback-msg error";
                    feedbackEl.textContent = data.message || `Lỗi: ${data.code || 'UNKNOWN'}`;
                }
            }
        } catch (err) {
            if (feedbackEl) {
                feedbackEl.className = "feedback-msg error";
                feedbackEl.textContent = `Lỗi kết nối máy chủ: ${err.message || err}`;
            }
        } finally {
            if (DOM.btnSubmitAddVehicleWatchlist) DOM.btnSubmitAddVehicleWatchlist.disabled = false;
        }
    }

    function resetAddVehicleForm() {
        if (DOM.inputNewVehiclePlate) DOM.inputNewVehiclePlate.value = "";
        if (DOM.plateNormalizedBadge) DOM.plateNormalizedBadge.textContent = "--";
        if (DOM.inputNewVehicleName) DOM.inputNewVehicleName.value = "";
        if (DOM.inputNewVehicleOwner) DOM.inputNewVehicleOwner.value = "";
        if (DOM.inputNewVehicleNotes) DOM.inputNewVehicleNotes.value = "";
        if (DOM.selectNewVehicleType) DOM.selectNewVehicleType.value = "car";
        if (DOM.selectNewVehicleStatus) DOM.selectNewVehicleStatus.value = "active";
        if (DOM.addVehicleFeedback) {
            DOM.addVehicleFeedback.className = "feedback-msg";
            DOM.addVehicleFeedback.textContent = "";
        }
    }

    /**
     * Initialize Watchlist Event Listeners.
     */
    function initWatchlistEvents() {
        // Navigation clicks
        document.querySelectorAll("[data-nav]").forEach(btn => {
            btn.addEventListener("click", () => {
                const navKey = btn.getAttribute("data-nav");
                navigateTo(navKey);
            });
        });

        // Tabs
        if (DOM.tabBtnWatchlistFace) {
            DOM.tabBtnWatchlistFace.addEventListener("click", () => switchWatchlistTab("face"));
        }
        if (DOM.tabBtnWatchlistVehicle) {
            DOM.tabBtnWatchlistVehicle.addEventListener("click", () => switchWatchlistTab("vehicle"));
        }

        // Refresh
        if (DOM.btnRefreshWatchlist) {
            DOM.btnRefreshWatchlist.addEventListener("click", () => {
                loadWatchlist();
                showWatchlistBanner("Đã làm mới dữ liệu Watchlist.", "info");
            });
        }

        // Face Filter Events
        if (DOM.faceSearchInput) {
            DOM.faceSearchInput.addEventListener("input", (e) => {
                watchlistState.faceFilter.search = e.target.value;
                renderFaceTable();
            });
        }
        if (DOM.faceStatusFilter) {
            DOM.faceStatusFilter.addEventListener("change", (e) => {
                watchlistState.faceFilter.status = e.target.value;
                renderFaceTable();
            });
        }
        if (DOM.faceSortFilter) {
            DOM.faceSortFilter.addEventListener("change", (e) => {
                watchlistState.faceFilter.sort = e.target.value;
                renderFaceTable();
            });
        }

        // Vehicle Filter Events
        if (DOM.vehicleSearchInput) {
            DOM.vehicleSearchInput.addEventListener("input", (e) => {
                watchlistState.vehicleFilter.search = e.target.value;
                renderVehicleTable();
            });
        }
        if (DOM.vehicleTypeFilter) {
            DOM.vehicleTypeFilter.addEventListener("change", (e) => {
                watchlistState.vehicleFilter.type = e.target.value;
                renderVehicleTable();
            });
        }
        if (DOM.vehicleStatusFilter) {
            DOM.vehicleStatusFilter.addEventListener("change", (e) => {
                watchlistState.vehicleFilter.status = e.target.value;
                renderVehicleTable();
            });
        }

        // Retry buttons
        if (DOM.btnRetryLoadFaces) DOM.btnRetryLoadFaces.addEventListener("click", loadWatchlist);
        if (DOM.btnRetryLoadVehicles) DOM.btnRetryLoadVehicles.addEventListener("click", loadWatchlist);

        // Open Add Modals
        if (DOM.btnOpenAddFaceModal) {
            DOM.btnOpenAddFaceModal.addEventListener("click", () => {
                resetAddFaceForm();
                if (DOM.modalAddFaceWatchlist) DOM.modalAddFaceWatchlist.style.display = "flex";
            });
        }
        if (DOM.btnEmptyAddFace) {
            DOM.btnEmptyAddFace.addEventListener("click", () => {
                resetAddFaceForm();
                if (DOM.modalAddFaceWatchlist) DOM.modalAddFaceWatchlist.style.display = "flex";
            });
        }

        if (DOM.btnOpenAddVehicleModal) {
            DOM.btnOpenAddVehicleModal.addEventListener("click", () => {
                resetAddVehicleForm();
                if (DOM.modalAddVehicleWatchlist) DOM.modalAddVehicleWatchlist.style.display = "flex";
            });
        }
        if (DOM.btnEmptyAddVehicle) {
            DOM.btnEmptyAddVehicle.addEventListener("click", () => {
                resetAddVehicleForm();
                if (DOM.modalAddVehicleWatchlist) DOM.modalAddVehicleWatchlist.style.display = "flex";
            });
        }

        // Close Add Face Modal
        if (DOM.btnCloseAddFaceWatchlist) {
            DOM.btnCloseAddFaceWatchlist.addEventListener("click", () => {
                if (DOM.modalAddFaceWatchlist) DOM.modalAddFaceWatchlist.style.display = "none";
            });
        }
        if (DOM.btnCancelAddFaceWatchlist) {
            DOM.btnCancelAddFaceWatchlist.addEventListener("click", () => {
                if (DOM.modalAddFaceWatchlist) DOM.modalAddFaceWatchlist.style.display = "none";
            });
        }

        // Close Add Vehicle Modal
        if (DOM.btnCloseAddVehicleWatchlist) {
            DOM.btnCloseAddVehicleWatchlist.addEventListener("click", () => {
                if (DOM.modalAddVehicleWatchlist) DOM.modalAddVehicleWatchlist.style.display = "none";
            });
        }
        if (DOM.btnCancelAddVehicleWatchlist) {
            DOM.btnCancelAddVehicleWatchlist.addEventListener("click", () => {
                if (DOM.modalAddVehicleWatchlist) DOM.modalAddVehicleWatchlist.style.display = "none";
            });
        }

        // Realtime plate normalization in modal
        if (DOM.inputNewVehiclePlate) {
            DOM.inputNewVehiclePlate.addEventListener("input", (e) => {
                const raw = e.target.value.toUpperCase();
                e.target.value = raw;
                const norm = raw.replace(/[^A-Za-z0-9]/g, "");
                if (DOM.plateNormalizedBadge) {
                    DOM.plateNormalizedBadge.textContent = norm || "--";
                }
            });
        }

        // Form submits
        if (DOM.btnSubmitAddFaceWatchlist) {
            DOM.btnSubmitAddFaceWatchlist.addEventListener("click", submitAddFaceWatchlist);
        }
        if (DOM.btnSubmitAddVehicleWatchlist) {
            DOM.btnSubmitAddVehicleWatchlist.addEventListener("click", submitAddVehicleWatchlist);
        }

        // Drawers Close & Actions
        if (DOM.btnCloseFaceDrawer) DOM.btnCloseFaceDrawer.addEventListener("click", closeAllDrawers);
        if (DOM.btnCloseVehicleDrawer) DOM.btnCloseVehicleDrawer.addEventListener("click", closeAllDrawers);
        if (DOM.drawerBackdrop) DOM.drawerBackdrop.addEventListener("click", closeAllDrawers);

        if (DOM.btnToggleFaceStatus) {
            DOM.btnToggleFaceStatus.addEventListener("click", () => {
                if (watchlistState.selectedFaceTarget) {
                    const current = watchlistState.selectedFaceTarget.is_selected !== false;
                    window.dattToggleFaceActive(watchlistState.selectedFaceTarget.id, !current);
                }
            });
        }

        if (DOM.btnToggleVehicleStatus) {
            DOM.btnToggleVehicleStatus.addEventListener("click", () => {
                if (watchlistState.selectedVehicle) {
                    const current = (watchlistState.selectedVehicle.status || "active") === "active";
                    window.dattToggleVehicleActive(watchlistState.selectedVehicle.id, current ? "disabled" : "active");
                }
            });
        }

        if (DOM.btnDeleteFaceTarget) {
            DOM.btnDeleteFaceTarget.addEventListener("click", () => {
                if (watchlistState.selectedFaceTarget) {
                    window.dattConfirmDelete("face", watchlistState.selectedFaceTarget.id, watchlistState.selectedFaceTarget.name);
                }
            });
        }

        if (DOM.btnEditVehicleItem) {
            DOM.btnEditVehicleItem.addEventListener("click", () => {
                if (watchlistState.selectedVehicle) {
                    window.dattOpenEditVehicleModal(watchlistState.selectedVehicle.id);
                }
            });
        }

        if (DOM.btnDeleteVehicleItem) {
            DOM.btnDeleteVehicleItem.addEventListener("click", () => {
                if (watchlistState.selectedVehicle) {
                    window.dattConfirmDelete("vehicle", watchlistState.selectedVehicle.id, watchlistState.selectedVehicle.plate_number);
                }
            });
        }

        // Edit Vehicle Watchlist Modal
        if (DOM.btnCloseEditVehicleWatchlist) {
            DOM.btnCloseEditVehicleWatchlist.addEventListener("click", () => {
                if (DOM.modalEditVehicleWatchlist) DOM.modalEditVehicleWatchlist.style.display = "none";
            });
        }
        if (DOM.btnCancelEditVehicleWatchlist) {
            DOM.btnCancelEditVehicleWatchlist.addEventListener("click", () => {
                if (DOM.modalEditVehicleWatchlist) DOM.modalEditVehicleWatchlist.style.display = "none";
            });
        }
        if (DOM.btnSubmitEditVehicleWatchlist) {
            DOM.btnSubmitEditVehicleWatchlist.addEventListener("click", submitEditVehicleWatchlist);
        }

        // Delete Confirm Modal
        if (DOM.btnCloseConfirmDelete) {
            DOM.btnCloseConfirmDelete.addEventListener("click", () => {
                if (DOM.modalConfirmDelete) DOM.modalConfirmDelete.style.display = "none";
            });
        }
        if (DOM.btnCancelConfirmDelete) {
            DOM.btnCancelConfirmDelete.addEventListener("click", () => {
                if (DOM.modalConfirmDelete) DOM.modalConfirmDelete.style.display = "none";
            });
        }
        if (DOM.btnExecuteConfirmDelete) {
            DOM.btnExecuteConfirmDelete.addEventListener("click", executeConfirmDelete);
        }

        // Dropzone
        initFaceDropzone();
    }

    /**
     * =========================================================================
     * CAMERA MANAGEMENT CONTROLLER & STATE
     * =========================================================================
     */
    const cameraMgmtState = {
        cameras: [],
        summary: { total: 0, online: 0, offline: 0, disabled: 0 },
        zones: [],
        isLoading: false,
        searchQuery: "",
        filterStatus: "all",
        filterType: "all",
        filterZone: "all",
        selectedCamera: null,
        deleteTargetCamera: null,
        testConnectionLoading: false
    };

    function showCameraBanner(msg, type = "success") {
        if (!DOM.cameraFeedbackBanner) return;
        DOM.cameraFeedbackBanner.textContent = msg;
        DOM.cameraFeedbackBanner.className = `watchlist-toast show ${type}`;
        DOM.cameraFeedbackBanner.style.display = "block";
        setTimeout(() => {
            DOM.cameraFeedbackBanner.classList.remove("show");
            setTimeout(() => {
                DOM.cameraFeedbackBanner.style.display = "none";
            }, 300);
        }, 3500);
    }

    async function loadManagementCameras(forceEmpty = false) {
        if (!DOM.cameraManagementScreen) return;
        cameraMgmtState.isLoading = true;

        if (DOM.cameraTableSkeleton) DOM.cameraTableSkeleton.style.display = "flex";
        if (DOM.cameraTableWrapper) DOM.cameraTableWrapper.style.display = "none";
        if (DOM.cameraTableEmpty) DOM.cameraTableEmpty.style.display = "none";
        if (DOM.cameraFilterEmpty) DOM.cameraFilterEmpty.style.display = "none";
        if (DOM.cameraTableError) DOM.cameraTableError.style.display = "none";

        if (forceEmpty) {
            cameraMgmtState.cameras = [];
            cameraMgmtState.summary = { total: 0, online: 0, offline: 0, disabled: 0 };
            cameraMgmtState.zones = [];
            cameraMgmtState.isLoading = false;
            updateCameraSummaryUi();
            filterAndRenderCameras();
            return;
        }

        try {
            const resp = await fetch(apiUrl("/api/cameras"));
            if (!resp.ok) {
                throw new Error(`Máy chủ trả về mã lỗi: ${resp.status}`);
            }
            const data = await resp.json();
            cameraMgmtState.cameras = data.cameras || [];
            cameraMgmtState.summary = data.summary || {
                total: cameraMgmtState.cameras.length,
                online: cameraMgmtState.cameras.filter(c => c.status === "online").length,
                offline: cameraMgmtState.cameras.filter(c => c.status === "offline").length,
                disabled: cameraMgmtState.cameras.filter(c => c.status === "disabled").length
            };
            cameraMgmtState.zones = data.zones || [];
            cameraMgmtState.isLoading = false;

            updateCameraSummaryUi();
            populateZoneFilterOptions();
            filterAndRenderCameras();
        } catch (err) {
            console.error("Lỗi khi tải danh sách camera:", err);
            cameraMgmtState.isLoading = false;
            if (DOM.cameraTableSkeleton) DOM.cameraTableSkeleton.style.display = "none";
            if (DOM.cameraTableError) {
                DOM.cameraTableError.style.display = "flex";
                if (DOM.cameraErrorMsg) DOM.cameraErrorMsg.textContent = err.message || "Không thể kết nối tới API quản lý camera.";
            }
        }
    }

    function updateCameraSummaryUi() {
        const { total, online, offline, disabled } = cameraMgmtState.summary;
        if (DOM.camTotalVal) DOM.camTotalVal.textContent = total;
        if (DOM.camOnlineVal) DOM.camOnlineVal.textContent = online;
        if (DOM.camOfflineVal) DOM.camOfflineVal.textContent = offline;
        if (DOM.camDisabledVal) DOM.camDisabledVal.textContent = disabled;
        if (DOM.navCameraCountBadge) DOM.navCameraCountBadge.textContent = total;
        if (DOM.navCameraCountBadgeEv) DOM.navCameraCountBadgeEv.textContent = total;
    }

    function populateZoneFilterOptions() {
        if (!DOM.cameraZoneFilter) return;
        const currentVal = DOM.cameraZoneFilter.value;
        const zones = new Set();
        cameraMgmtState.cameras.forEach(c => {
            const z = c.zone || c.location;
            if (z && z.trim()) {
                zones.add(z.trim());
            }
        });
        (cameraMgmtState.zones || []).forEach(z => zones.add(z));

        let html = '<option value="all">Tất cả khu vực</option>';
        zones.forEach(z => {
            html += `<option value="${escapeHtml(z)}">${escapeHtml(z)}</option>`;
        });
        DOM.cameraZoneFilter.innerHTML = html;
        if ([...zones].includes(currentVal)) {
            DOM.cameraZoneFilter.value = currentVal;
        }
    }

    function filterAndRenderCameras() {
        if (!DOM.cameraTableBody) return;
        if (DOM.cameraTableSkeleton) DOM.cameraTableSkeleton.style.display = "none";

        const q = (cameraMgmtState.searchQuery || "").toLowerCase().trim();
        const s = cameraMgmtState.filterStatus || "all";
        const t = cameraMgmtState.filterType || "all";
        const z = cameraMgmtState.filterZone || "all";

        const totalAvailable = cameraMgmtState.cameras.length;

        if (totalAvailable === 0) {
            if (DOM.cameraTableWrapper) DOM.cameraTableWrapper.style.display = "none";
            if (DOM.cameraFilterEmpty) DOM.cameraFilterEmpty.style.display = "none";
            if (DOM.cameraTableEmpty) DOM.cameraTableEmpty.style.display = "flex";
            return;
        }

        const filtered = cameraMgmtState.cameras.filter(cam => {
            const camZone = (cam.zone || cam.location || "").toLowerCase();
            if (s !== "all" && cam.status !== s) return false;
            if (t !== "all" && (cam.source_type || "").toLowerCase() !== t.toLowerCase()) return false;
            if (z !== "all" && camZone !== z.toLowerCase()) return false;
            if (q) {
                const matchName = (cam.name || "").toLowerCase().includes(q);
                const matchId = (cam.id || "").toLowerCase().includes(q);
                const matchLoc = camZone.includes(q);
                const matchUrl = (cam.url || "").toLowerCase().includes(q);
                if (!matchName && !matchId && !matchLoc && !matchUrl) return false;
            }
            return true;
        });

        if (filtered.length === 0) {
            if (DOM.cameraTableWrapper) DOM.cameraTableWrapper.style.display = "none";
            if (DOM.cameraTableEmpty) DOM.cameraTableEmpty.style.display = "none";
            if (DOM.cameraFilterEmpty) DOM.cameraFilterEmpty.style.display = "flex";
            return;
        }

        if (DOM.cameraTableEmpty) DOM.cameraTableEmpty.style.display = "none";
        if (DOM.cameraFilterEmpty) DOM.cameraFilterEmpty.style.display = "none";
        if (DOM.cameraTableWrapper) DOM.cameraTableWrapper.style.display = "block";

        DOM.cameraTableBody.innerHTML = filtered.map(cam => {
            const statusClass = cam.status === "online" ? "status-online" : (cam.status === "offline" ? "status-offline" : "status-disabled");
            const statusLabel = cam.status === "online" ? "🟢 Hoạt động" : (cam.status === "offline" ? "🔴 Mất kết nối" : "⏸️ Đã tắt");
            const dotClass = cam.status === "online" ? "dot-online" : (cam.status === "offline" ? "dot-offline" : "dot-disabled");
            const toggleIcon = cam.status === "disabled" ? "▶️" : "⏸️";
            const toggleTitle = cam.status === "disabled" ? "Kích hoạt camera" : "Tắt camera";
            const zoneDisplay = cam.zone || cam.location || "Chưa gán";

            const thumbContent = cam.thumbnail 
                ? `<img src="${escapeHtml(cam.thumbnail)}" alt="${escapeHtml(cam.name)}" class="cam-table-thumb-img" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" loading="lazy"><span class="cam-table-thumb-fallback" style="display:none;">📹</span>`
                : `<span class="cam-table-thumb-fallback">📹</span>`;

            return `
                <tr data-cam-id="${escapeHtml(cam.id)}">
                    <td>
                        <div class="cam-table-thumb-wrap">
                            ${thumbContent}
                            <span class="cam-table-dot ${dotClass}" title="${statusLabel}"></span>
                        </div>
                    </td>
                    <td>
                        <div class="cam-name-cell">
                            <span class="cam-cell-title">${escapeHtml(cam.name)}</span>
                            <span class="cam-cell-id font-mono">${escapeHtml(cam.id)}</span>
                        </div>
                    </td>
                    <td>
                        <span class="font-mono text-muted" style="font-size: 0.82rem;">${escapeHtml(cam.id)}</span>
                    </td>
                    <td>
                        <span class="zone-pill">📍 ${escapeHtml(zoneDisplay)}</span>
                    </td>
                    <td>
                        <span class="type-pill ${(cam.source_type || 'rtsp').toLowerCase()}">${escapeHtml((cam.source_type || 'RTSP').toUpperCase())}</span>
                    </td>
                    <td>
                        <span class="status-pill ${statusClass}">${statusLabel}</span>
                    </td>
                    <td>
                        <span class="cam-cell-time">${escapeHtml(cam.last_active || "Vừa xong")}</span>
                    </td>
                    <td>
                        <div class="table-actions-cell">
                            <button type="button" class="row-action-btn" title="Mở giám sát trực tiếp" onclick="window.dattLaunchMonitoring('${escapeHtml(cam.id)}')">
                                🖥️
                            </button>
                            <button type="button" class="row-action-btn" title="Xem chi tiết" onclick="window.dattOpenCamDrawer('${escapeHtml(cam.id)}')">
                                👁️
                            </button>
                            <button type="button" class="row-action-btn" title="Chỉnh sửa" onclick="window.dattOpenEditCamModal('${escapeHtml(cam.id)}')">
                                ✏️
                            </button>
                            <button type="button" class="row-action-btn" title="${toggleTitle}" onclick="window.dattToggleCamStatus('${escapeHtml(cam.id)}')">
                                ${toggleIcon}
                            </button>
                            <button type="button" class="row-action-btn btn-delete" title="Xóa" onclick="window.dattOpenDeleteCamModal('${escapeHtml(cam.id)}')">
                                🗑️
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    window.dattLaunchMonitoring = function(camId) {
        const cam = cameraMgmtState.cameras.find(c => c.id === camId);
        if (!cam) return;
        window.dattCloseCamDrawer();
        window.dattSelectCamera(cam.name, cam.url, (cam.source_type || "rtsp").toLowerCase(), cam.zone || cam.location || "Camera", null, null, cam.id);
    };

    window.dattOpenCamDrawer = async function(camId) {
        let cam = cameraMgmtState.cameras.find(c => c.id === camId);
        try {
            const resp = await fetch(apiUrl(`/api/cameras/${encodeURIComponent(camId)}`));
            if (resp.ok) {
                const data = await resp.json();
                if (data.camera) {
                    cam = data.camera;
                    const idx = cameraMgmtState.cameras.findIndex(c => c.id === camId);
                    if (idx !== -1) cameraMgmtState.cameras[idx] = cam;
                }
            }
        } catch (e) {}
        if (!cam) return;
        cameraMgmtState.selectedCamera = cam;
        const zoneDisplay = cam.zone || cam.location || "Chưa gán";

        if (DOM.camDrawerTitle) DOM.camDrawerTitle.textContent = cam.name;
        if (DOM.camDrawerId) DOM.camDrawerId.textContent = cam.id;
        if (DOM.camDrawerStatus) {
            const statusClass = cam.status === "online" ? "status-online" : (cam.status === "offline" ? "status-offline" : "status-disabled");
            const statusLabel = cam.status === "online" ? "Online" : (cam.status === "offline" ? "Offline" : "Disabled");
            DOM.camDrawerStatus.className = `status-pill ${statusClass}`;
            DOM.camDrawerStatus.textContent = statusLabel;
        }
        if (DOM.camDrawerPreviewType) DOM.camDrawerPreviewType.textContent = (cam.source_type || "RTSP").toUpperCase();
        if (DOM.camDrawerPreviewUrl) DOM.camDrawerPreviewUrl.textContent = cam.url || "--";
        if (DOM.camDrawerGraphicLabel) DOM.camDrawerGraphicLabel.textContent = `Luồng trực tiếp: ${cam.name}`;
        if (DOM.camDrawerPingBadge) {
            DOM.camDrawerPingBadge.textContent = cam.status === "online" ? "Độ trễ: 38ms (Rất tốt)" : (cam.status === "disabled" ? "Tạm ngưng" : "Mất kết nối");
        }
        if (DOM.camDrawerStreamHealth) {
            DOM.camDrawerStreamHealth.textContent = cam.status === "online" ? "Ổn định (1080p @ 25 FPS)" : "Không khả dụng";
        }
        if (DOM.camDrawerUrl) DOM.camDrawerUrl.textContent = cam.url || "--";
        if (DOM.camDrawerZone) DOM.camDrawerZone.textContent = zoneDisplay;
        if (DOM.camDrawerType) DOM.camDrawerType.textContent = (cam.source_type || "RTSP").toUpperCase();
        if (DOM.camDrawerCreated) DOM.camDrawerCreated.textContent = cam.created_at || "2026-09-01";
        if (DOM.camDrawerLastActive) DOM.camDrawerLastActive.textContent = cam.last_active || "Vừa xong";
        if (DOM.camDrawerDesc) DOM.camDrawerDesc.textContent = cam.description || "Không có mô tả bổ sung.";
        if (DOM.camDrawerToggleText) {
            DOM.camDrawerToggleText.textContent = cam.status === "disabled" ? "Kích hoạt" : "Tạm ngưng";
        }

        if (DOM.drawerCameraDetail) {
            DOM.drawerCameraDetail.classList.add("open");
        }
    };

    window.dattCloseCamDrawer = function() {
        if (DOM.drawerCameraDetail) {
            DOM.drawerCameraDetail.classList.remove("open");
        }
    };

    window.dattToggleCamStatus = async function(camId) {
        const cam = cameraMgmtState.cameras.find(c => c.id === camId);
        if (!cam) return;
        const willEnable = cam.status === "disabled";
        const endpoint = willEnable ? `/api/cameras/${encodeURIComponent(camId)}/enable` : `/api/cameras/${encodeURIComponent(camId)}/disable`;

        try {
            const resp = await fetch(apiUrl(endpoint), {
                method: "POST"
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                let errMsg = errData.detail || errData.message || "Cập nhật trạng thái camera thất bại.";
                if (resp.status === 409 && errData.detail === "CAMERA_ACTIVE_STOP_FIRST") {
                    errMsg = "Camera đang được sử dụng trong phiên giám sát trực tiếp. Vui lòng dừng giám sát trước khi tắt camera.";
                }
                throw new Error(errMsg);
            }
            const data = await resp.json();
            const updated = data.camera;
            if (updated) {
                cam.status = updated.status;
                cam.last_active = updated.last_active;
            } else {
                cam.status = willEnable ? "online" : "disabled";
            }

            cameraMgmtState.summary = {
                total: cameraMgmtState.cameras.length,
                online: cameraMgmtState.cameras.filter(c => c.status === "online").length,
                offline: cameraMgmtState.cameras.filter(c => c.status === "offline").length,
                disabled: cameraMgmtState.cameras.filter(c => c.status === "disabled").length
            };
            updateCameraSummaryUi();
            filterAndRenderCameras();

            if (cameraMgmtState.selectedCamera && cameraMgmtState.selectedCamera.id === camId) {
                window.dattOpenCamDrawer(camId);
            }
            showCameraBanner(`Đã chuyển camera "${cam.name}" sang trạng thái: ${willEnable ? 'Hoạt động' : 'Tạm ngưng'}.`, "success");
        } catch (err) {
            showCameraBanner(err.message, "error");
        }
    };

    window.dattOpenEditCamModal = function(camId) {
        window.dattCloseCamDrawer();
        const cam = cameraMgmtState.cameras.find(c => c.id === camId);
        if (!cam) return;

        if (DOM.editCamIdBadge) DOM.editCamIdBadge.textContent = cam.id;
        if (DOM.inputEditCamId) DOM.inputEditCamId.value = cam.id;
        if (DOM.inputEditCamName) DOM.inputEditCamName.value = cam.name;
        if (DOM.inputEditCamUrl) DOM.inputEditCamUrl.value = cam.url;
        if (DOM.selectEditCamType) DOM.selectEditCamType.value = (cam.source_type || "rtsp").toLowerCase();
        if (DOM.selectEditCamStatus) DOM.selectEditCamStatus.value = cam.status || "online";
        if (DOM.inputEditCamZone) DOM.inputEditCamZone.value = cam.zone || cam.location || "";
        if (DOM.inputEditCamDesc) DOM.inputEditCamDesc.value = cam.description || "";
        if (DOM.editCamFormFeedback) DOM.editCamFormFeedback.textContent = "";
        if (DOM.testConnResultEdit) {
            DOM.testConnResultEdit.innerHTML = '<span class="status-hint">Bấm "Kiểm tra kết nối" để xác thực phản hồi luồng stream.</span>';
        }

        if (DOM.modalEditCamera) DOM.modalEditCamera.style.display = "flex";
    };

    window.dattOpenDeleteCamModal = function(camId) {
        window.dattCloseCamDrawer();
        const cam = cameraMgmtState.cameras.find(c => c.id === camId);
        if (!cam) return;
        cameraMgmtState.deleteTargetCamera = cam;
        const zoneDisplay = cam.zone || cam.location || "Chưa gán";

        if (DOM.deleteCamTargetName) DOM.deleteCamTargetName.textContent = cam.name;
        if (DOM.deleteCamTargetId) DOM.deleteCamTargetId.textContent = `ID: ${cam.id} • ${(cam.source_type || 'RTSP').toUpperCase()} • ${zoneDisplay}`;
        if (DOM.deleteCamFeedback) DOM.deleteCamFeedback.textContent = "";

        if (DOM.modalDeleteCamera) DOM.modalDeleteCamera.style.display = "flex";
    };

    function openAddCameraModal() {
        if (DOM.inputAddCamName) DOM.inputAddCamName.value = "";
        if (DOM.inputAddCamUrl) DOM.inputAddCamUrl.value = "";
        if (DOM.selectAddCamType) DOM.selectAddCamType.value = "rtsp";
        if (DOM.selectAddCamStatus) DOM.selectAddCamStatus.value = "online";
        if (DOM.inputAddCamZone) DOM.inputAddCamZone.value = "";
        if (DOM.inputAddCamDesc) DOM.inputAddCamDesc.value = "";
        if (DOM.addCamFormFeedback) DOM.addCamFormFeedback.textContent = "";
        if (DOM.testConnResultAdd) {
            DOM.testConnResultAdd.innerHTML = '<span class="status-hint">Nhập Source URL và bấm "Kiểm tra kết nối" để xác thực luồng stream trước khi lưu.</span>';
        }
        if (DOM.modalAddCamera) DOM.modalAddCamera.style.display = "flex";
    }

    async function testConnection(url, sourceType, resultEl, btnEl) {
        if (!url) {
            resultEl.innerHTML = '<span class="text-danger font-semibold">⚠️ Vui lòng nhập Source URL trước khi kiểm tra.</span>';
            return;
        }
        if (btnEl) btnEl.disabled = true;
        resultEl.innerHTML = '<span class="text-highlight">🔄 Đang kiểm tra kết nối tới thiết bị...</span>';

        try {
            const resp = await fetch(apiUrl("/api/camera_management/test_connection"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: url, source_type: sourceType })
            });
            const data = await resp.json();
            if (data.success) {
                const msg = data.message || `Kết nối thành công (mã: ${data.code || 'OK'})`;
                resultEl.innerHTML = `<span class="text-success font-semibold">✓ ${escapeHtml(msg)} (${data.latency_ms || 0}ms)</span>`;
            } else {
                const msg = data.message || `Kết nối thất bại (mã: ${data.code || 'ERR_CONNECTION_FAILED'})`;
                resultEl.innerHTML = `<span class="text-danger font-semibold">✕ ${escapeHtml(msg)}</span>`;
            }
        } catch (err) {
            resultEl.innerHTML = `<span class="text-danger font-semibold">✕ Lỗi khi kiểm tra kết nối: ${escapeHtml(err.message)}</span>`;
        } finally {
            if (btnEl) btnEl.disabled = false;
        }
    }

    async function submitAddCamera() {
        const name = (DOM.inputAddCamName ? DOM.inputAddCamName.value : "").trim();
        const url = (DOM.inputAddCamUrl ? DOM.inputAddCamUrl.value : "").trim();
        const sourceType = DOM.selectAddCamType ? DOM.selectAddCamType.value : "rtsp";
        const status = DOM.selectAddCamStatus ? DOM.selectAddCamStatus.value : "online";
        const location = (DOM.inputAddCamZone ? DOM.inputAddCamZone.value : "").trim();
        const description = (DOM.inputAddCamDesc ? DOM.inputAddCamDesc.value : "").trim();

        if (!name || !url) {
            if (DOM.addCamFormFeedback) {
                DOM.addCamFormFeedback.className = "feedback-msg error";
                DOM.addCamFormFeedback.textContent = "Vui lòng nhập đầy đủ Tên camera và Source URL (*).";
            }
            return;
        }

        if (DOM.btnSubmitAddCamera) DOM.btnSubmitAddCamera.disabled = true;
        if (DOM.addCamFormFeedback) {
            DOM.addCamFormFeedback.className = "feedback-msg";
            DOM.addCamFormFeedback.textContent = "Đang thêm camera...";
        }

        try {
            const resp = await fetch(apiUrl("/api/cameras"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name,
                    url,
                    source_url: url,
                    source_type: sourceType,
                    status,
                    zone: location,
                    location: location,
                    description
                })
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || errData.message || "Không thể thêm camera.");
            }
            if (DOM.modalAddCamera) DOM.modalAddCamera.style.display = "none";
            showCameraBanner(`Đã thêm thành công camera "${name}".`, "success");
            await loadManagementCameras();
        } catch (err) {
            if (DOM.addCamFormFeedback) {
                DOM.addCamFormFeedback.className = "feedback-msg error";
                DOM.addCamFormFeedback.textContent = err.message;
            }
        } finally {
            if (DOM.btnSubmitAddCamera) DOM.btnSubmitAddCamera.disabled = false;
        }
    }

    async function submitEditCamera() {
        const id = DOM.inputEditCamId ? DOM.inputEditCamId.value : "";
        const name = (DOM.inputEditCamName ? DOM.inputEditCamName.value : "").trim();
        const url = (DOM.inputEditCamUrl ? DOM.inputEditCamUrl.value : "").trim();
        const sourceType = DOM.selectEditCamType ? DOM.selectEditCamType.value : "rtsp";
        const status = DOM.selectEditCamStatus ? DOM.selectEditCamStatus.value : "online";
        const location = (DOM.inputEditCamZone ? DOM.inputEditCamZone.value : "").trim();
        const description = (DOM.inputEditCamDesc ? DOM.inputEditCamDesc.value : "").trim();

        if (!id || !name || !url) {
            if (DOM.editCamFormFeedback) {
                DOM.editCamFormFeedback.className = "feedback-msg error";
                DOM.editCamFormFeedback.textContent = "Vui lòng nhập đầy đủ Tên camera và Source URL (*).";
            }
            return;
        }

        if (DOM.btnSubmitEditCamera) DOM.btnSubmitEditCamera.disabled = true;
        if (DOM.editCamFormFeedback) {
            DOM.editCamFormFeedback.className = "feedback-msg";
            DOM.editCamFormFeedback.textContent = "Đang lưu thay đổi...";
        }

        try {
            const resp = await fetch(apiUrl(`/api/cameras/${encodeURIComponent(id)}`), {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name,
                    url,
                    source_url: url,
                    source_type: sourceType,
                    status,
                    zone: location,
                    location: location,
                    description
                })
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                let errMsg = errData.detail || errData.message || "Không thể cập nhật camera.";
                if (resp.status === 409 && errData.detail === "CAMERA_ACTIVE_STOP_FIRST") {
                    errMsg = "Camera đang được sử dụng trong phiên giám sát trực tiếp. Vui lòng dừng giám sát trước khi cập nhật trạng thái.";
                }
                throw new Error(errMsg);
            }
            if (DOM.modalEditCamera) DOM.modalEditCamera.style.display = "none";
            showCameraBanner(`Đã cập nhật cấu hình camera "${name}".`, "success");
            await loadManagementCameras();
        } catch (err) {
            if (DOM.editCamFormFeedback) {
                DOM.editCamFormFeedback.className = "feedback-msg error";
                DOM.editCamFormFeedback.textContent = err.message;
            }
        } finally {
            if (DOM.btnSubmitEditCamera) DOM.btnSubmitEditCamera.disabled = false;
        }
    }

    async function executeDeleteCamera() {
        if (!cameraMgmtState.deleteTargetCamera) return;
        const cam = cameraMgmtState.deleteTargetCamera;

        if (DOM.btnConfirmDeleteCamera) DOM.btnConfirmDeleteCamera.disabled = true;
        if (DOM.deleteCamFeedback) {
            DOM.deleteCamFeedback.className = "feedback-msg";
            DOM.deleteCamFeedback.textContent = "Đang xóa camera...";
        }

        try {
            const resp = await fetch(apiUrl(`/api/cameras/${encodeURIComponent(cam.id)}`), {
                method: "DELETE"
            });
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                let errMsg = errData.detail || errData.message || "Không thể xóa camera.";
                if (resp.status === 409) {
                    if (errData.detail === "CAMERA_ACTIVE_STOP_FIRST") {
                        errMsg = "Camera đang được sử dụng trong phiên giám sát trực tiếp. Vui lòng dừng giám sát trước khi xóa camera.";
                    } else if (errData.detail === "CAMERA_REFERENCED_OR_CONFLICT") {
                        errMsg = "Không thể xóa camera đã có dữ liệu sự kiện lịch sử tham chiếu (bảo vệ toàn vẹn dữ liệu).";
                    }
                }
                throw new Error(errMsg);
            }
            if (DOM.modalDeleteCamera) DOM.modalDeleteCamera.style.display = "none";
            showCameraBanner(`Đã xóa camera "${cam.name}" khỏi hệ thống.`, "success");
            cameraMgmtState.deleteTargetCamera = null;
            await loadManagementCameras();
        } catch (err) {
            if (DOM.deleteCamFeedback) {
                DOM.deleteCamFeedback.className = "feedback-msg error";
                DOM.deleteCamFeedback.textContent = err.message;
            }
        } finally {
            if (DOM.btnConfirmDeleteCamera) DOM.btnConfirmDeleteCamera.disabled = false;
        }
    }

    function initCameraManagementEvents() {
        // Toolbar actions
        if (DOM.btnOpenAddCameraModal) {
            DOM.btnOpenAddCameraModal.addEventListener("click", openAddCameraModal);
        }
        if (DOM.btnToolbarAddCamera) {
            DOM.btnToolbarAddCamera.addEventListener("click", openAddCameraModal);
        }
        if (DOM.btnEmptyAddCamera) {
            DOM.btnEmptyAddCamera.addEventListener("click", openAddCameraModal);
        }
        if (DOM.btnSwitchToSelection) {
            DOM.btnSwitchToSelection.addEventListener("click", () => {
                const url = new URL(window.location);
                url.pathname = "/";
                url.search = "";
                history.pushState(null, "", url.toString());
                setUiState(UI_STATE.SELECT_CAMERA);
            });
        }
        if (DOM.btnRefreshCameras) {
            DOM.btnRefreshCameras.addEventListener("click", () => {
                loadManagementCameras();
                showCameraBanner("Đã làm mới danh sách camera.", "info");
            });
        }
        if (DOM.btnRetryLoadCameras) {
            DOM.btnRetryLoadCameras.addEventListener("click", () => {
                loadManagementCameras();
            });
        }

        // Search & Filters
        if (DOM.cameraSearchInput) {
            DOM.cameraSearchInput.addEventListener("input", (e) => {
                cameraMgmtState.searchQuery = e.target.value;
                filterAndRenderCameras();
            });
        }
        if (DOM.cameraStatusFilter) {
            DOM.cameraStatusFilter.addEventListener("change", (e) => {
                cameraMgmtState.filterStatus = e.target.value;
                filterAndRenderCameras();
            });
        }
        if (DOM.cameraTypeFilter) {
            DOM.cameraTypeFilter.addEventListener("change", (e) => {
                cameraMgmtState.filterType = e.target.value;
                filterAndRenderCameras();
            });
        }
        if (DOM.cameraZoneFilter) {
            DOM.cameraZoneFilter.addEventListener("change", (e) => {
                cameraMgmtState.filterZone = e.target.value;
                filterAndRenderCameras();
            });
        }
        if (DOM.btnResetCameraFilters) {
            DOM.btnResetCameraFilters.addEventListener("click", () => {
                cameraMgmtState.searchQuery = "";
                cameraMgmtState.filterStatus = "all";
                cameraMgmtState.filterType = "all";
                cameraMgmtState.filterZone = "all";
                if (DOM.cameraSearchInput) DOM.cameraSearchInput.value = "";
                if (DOM.cameraStatusFilter) DOM.cameraStatusFilter.value = "all";
                if (DOM.cameraTypeFilter) DOM.cameraTypeFilter.value = "all";
                if (DOM.cameraZoneFilter) DOM.cameraZoneFilter.value = "all";
                filterAndRenderCameras();
            });
        }

        // Drawer Detail Events
        if (DOM.btnCloseCameraDrawer) {
            DOM.btnCloseCameraDrawer.addEventListener("click", window.dattCloseCamDrawer);
        }
        if (DOM.btnLaunchMonitoringFromDrawer) {
            DOM.btnLaunchMonitoringFromDrawer.addEventListener("click", () => {
                if (cameraMgmtState.selectedCamera) {
                    const cam = cameraMgmtState.selectedCamera;
                    window.dattCloseCamDrawer();
                    window.dattSelectCamera(cam.name, cam.url, (cam.source_type || "rtsp").toLowerCase(), cam.zone || cam.location || "Camera", null, null, cam.id);
                }
            });
        }
        if (DOM.btnEditCamFromDrawer) {
            DOM.btnEditCamFromDrawer.addEventListener("click", () => {
                if (cameraMgmtState.selectedCamera) {
                    window.dattOpenEditCamModal(cameraMgmtState.selectedCamera.id);
                }
            });
        }
        if (DOM.btnToggleStatusFromDrawer) {
            DOM.btnToggleStatusFromDrawer.addEventListener("click", () => {
                if (cameraMgmtState.selectedCamera) {
                    window.dattToggleCamStatus(cameraMgmtState.selectedCamera.id);
                }
            });
        }
        if (DOM.btnDeleteCamFromDrawer) {
            DOM.btnDeleteCamFromDrawer.addEventListener("click", () => {
                if (cameraMgmtState.selectedCamera) {
                    window.dattOpenDeleteCamModal(cameraMgmtState.selectedCamera.id);
                }
            });
        }

        // Add Camera Modal Events
        if (DOM.btnCloseAddCameraModal) {
            DOM.btnCloseAddCameraModal.addEventListener("click", () => {
                if (DOM.modalAddCamera) DOM.modalAddCamera.style.display = "none";
            });
        }
        if (DOM.btnCancelAddCamera) {
            DOM.btnCancelAddCamera.addEventListener("click", () => {
                if (DOM.modalAddCamera) DOM.modalAddCamera.style.display = "none";
            });
        }
        if (DOM.btnTestConnAdd) {
            DOM.btnTestConnAdd.addEventListener("click", () => {
                const url = (DOM.inputAddCamUrl ? DOM.inputAddCamUrl.value : "").trim();
                const type = DOM.selectAddCamType ? DOM.selectAddCamType.value : "rtsp";
                testConnection(url, type, DOM.testConnResultAdd, DOM.btnTestConnAdd);
            });
        }
        if (DOM.btnSubmitAddCamera) {
            DOM.btnSubmitAddCamera.addEventListener("click", submitAddCamera);
        }

        // Edit Camera Modal Events
        if (DOM.btnCloseEditCameraModal) {
            DOM.btnCloseEditCameraModal.addEventListener("click", () => {
                if (DOM.modalEditCamera) DOM.modalEditCamera.style.display = "none";
            });
        }
        if (DOM.btnCancelEditCamera) {
            DOM.btnCancelEditCamera.addEventListener("click", () => {
                if (DOM.modalEditCamera) DOM.modalEditCamera.style.display = "none";
            });
        }
        if (DOM.btnTestConnEdit) {
            DOM.btnTestConnEdit.addEventListener("click", () => {
                const url = (DOM.inputEditCamUrl ? DOM.inputEditCamUrl.value : "").trim();
                const type = DOM.selectEditCamType ? DOM.selectEditCamType.value : "rtsp";
                testConnection(url, type, DOM.testConnResultEdit, DOM.btnTestConnEdit);
            });
        }
        if (DOM.btnSubmitEditCamera) {
            DOM.btnSubmitEditCamera.addEventListener("click", submitEditCamera);
        }

        // Delete Camera Modal Events
        if (DOM.btnCloseDeleteCameraModal) {
            DOM.btnCloseDeleteCameraModal.addEventListener("click", () => {
                if (DOM.modalDeleteCamera) DOM.modalDeleteCamera.style.display = "none";
            });
        }
        if (DOM.btnCancelDeleteCamera) {
            DOM.btnCancelDeleteCamera.addEventListener("click", () => {
                if (DOM.modalDeleteCamera) DOM.modalDeleteCamera.style.display = "none";
            });
        }
        if (DOM.btnConfirmDeleteCamera) {
            DOM.btnConfirmDeleteCamera.addEventListener("click", executeDeleteCamera);
        }
    }

    /**
     * =========================================================================
     * EVENT CENTER CONTROLLER & STATE (TASK 2)
     * =========================================================================
     */
    const eventCenterState = {
        currentTab: "all",
        page: 1,
        pageSize: 20,
        sort: "desc",
        total: 0,
        filters: {
            camera: "",
            eventType: "",
            targetId: "",
            plate: "",
            watchlistMatch: "",
            notificationStatus: "",
            fromTime: "",
            toTime: ""
        },
        events: [],
        selectedEvent: null,
        isLoading: false
    };

    /**
     * Load Real Summary Card Metrics for Event Center.
     */
    async function loadEventCenterSummary() {
        try {
            const [respTotal, respFace, respPlate, respVehicle, respMatch] = await Promise.allSettled([
                fetch(apiUrl("/api/event_center/events?page_size=1")),
                fetch(apiUrl("/api/event_center/events?event_type=face&page_size=1")),
                fetch(apiUrl("/api/event_center/events?event_type=plate&page_size=1")),
                fetch(apiUrl("/api/event_center/events?event_type=vehicle&page_size=1")),
                fetch(apiUrl("/api/event_center/events?watchlist_match=true&page_size=1"))
            ]);

            let totalCount = 0;
            let faceCount = 0;
            let plateCount = 0;
            let vehicleCount = 0;
            let matchCount = 0;

            if (respTotal.status === "fulfilled" && respTotal.value.ok) {
                const d = await respTotal.value.json();
                totalCount = d.total || 0;
            }
            if (respFace.status === "fulfilled" && respFace.value.ok) {
                const d = await respFace.value.json();
                faceCount = d.total || 0;
            }
            if (respPlate.status === "fulfilled" && respPlate.value.ok) {
                const d = await respPlate.value.json();
                plateCount = d.total || 0;
            }
            if (respVehicle.status === "fulfilled" && respVehicle.value.ok) {
                const d = await respVehicle.value.json();
                vehicleCount = d.total || 0;
            }
            if (respMatch.status === "fulfilled" && respMatch.value.ok) {
                const d = await respMatch.value.json();
                matchCount = d.total || 0;
            }

            if (DOM.evTotalCount) DOM.evTotalCount.textContent = totalCount;
            if (DOM.evFaceCount) DOM.evFaceCount.textContent = faceCount;
            if (DOM.evPlateVehicleCount) DOM.evPlateVehicleCount.textContent = (plateCount + vehicleCount);
            if (DOM.evMatchCount) DOM.evMatchCount.textContent = matchCount;
            if (DOM.navEventCountBadge) DOM.navEventCountBadge.textContent = totalCount;
        } catch (e) {
            console.warn("Failed to load Event Center summary:", e);
        }
    }

    /**
     * Populate Camera Dropdown Filter in Event Center.
     */
    async function populateEventCameraOptions() {
        if (!DOM.eventFilterCamera) return;
        const currentVal = DOM.eventFilterCamera.value;

        let cameras = cameraMgmtState.cameras;
        if (!cameras || cameras.length === 0) {
            try {
                const resp = await fetch(apiUrl("/api/cameras"));
                if (resp.ok) {
                    const data = await resp.json();
                    cameras = data.cameras || [];
                }
            } catch (e) {}
        }

        let html = '<option value="">Tất cả Camera</option>';
        (cameras || []).forEach(cam => {
            html += `<option value="${escapeHtml(cam.id)}">${escapeHtml(cam.name)} (${escapeHtml(cam.id)})</option>`;
        });
        DOM.eventFilterCamera.innerHTML = html;
        if (currentVal) DOM.eventFilterCamera.value = currentVal;
    }

    /**
     * Switch Active Tab in Event Center.
     */
    function switchEventTab(tabName) {
        eventCenterState.currentTab = tabName;
        document.querySelectorAll(".event-tab-btn").forEach(btn => {
            if (btn.getAttribute("data-tab") === tabName) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });

        // Also sync eventFilterType dropdown if applicable
        if (DOM.eventFilterType) {
            DOM.eventFilterType.value = (tabName === "all" ? "" : tabName);
        }

        eventCenterState.page = 1;
        loadEventCenterEvents();
    }

    /**
     * Load Event Center Events from Backend API.
     */
    async function loadEventCenterEvents() {
        if (!DOM.eventCenterScreen) return;
        eventCenterState.isLoading = true;

        if (DOM.eventTableSkeleton) DOM.eventTableSkeleton.style.display = "flex";
        if (DOM.eventTableWrapper) DOM.eventTableWrapper.style.display = "none";
        if (DOM.eventTableEmpty) DOM.eventTableEmpty.style.display = "none";
        if (DOM.eventFilterEmpty) DOM.eventFilterEmpty.style.display = "none";
        if (DOM.eventTableError) DOM.eventTableError.style.display = "none";

        const params = new URLSearchParams();
        params.set("page", String(eventCenterState.page));
        params.set("page_size", String(eventCenterState.pageSize));
        params.set("sort", eventCenterState.sort || "desc");

        // Event Type determination: Tab takes precedence if specific, else dropdown
        if (eventCenterState.currentTab && eventCenterState.currentTab !== "all") {
            params.set("event_type", eventCenterState.currentTab);
        } else if (eventCenterState.filters.eventType) {
            params.set("event_type", eventCenterState.filters.eventType);
        }

        if (eventCenterState.filters.camera) {
            params.set("camera", eventCenterState.filters.camera);
        }
        if (eventCenterState.filters.targetId) {
            params.set("target_id", eventCenterState.filters.targetId);
        }
        if (eventCenterState.filters.plate) {
            params.set("plate", eventCenterState.filters.plate);
        }
        if (eventCenterState.filters.watchlistMatch) {
            params.set("watchlist_match", eventCenterState.filters.watchlistMatch);
        }
        if (eventCenterState.filters.notificationStatus) {
            params.set("notification_status", eventCenterState.filters.notificationStatus);
        }

        // Time Filters: backend requires timezone (ISO8601)
        if (eventCenterState.filters.fromTime) {
            try {
                const dt = new Date(eventCenterState.filters.fromTime);
                if (!isNaN(dt.getTime())) {
                    params.set("from", dt.toISOString());
                }
            } catch (e) {}
        }
        if (eventCenterState.filters.toTime) {
            try {
                const dt = new Date(eventCenterState.filters.toTime);
                if (!isNaN(dt.getTime())) {
                    params.set("to", dt.toISOString());
                }
            } catch (e) {}
        }

        try {
            const resp = await fetch(apiUrl(`/api/event_center/events?${params.toString()}`));
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                throw new Error(errData.detail || `Máy chủ trả về mã lỗi: ${resp.status}`);
            }
            const data = await resp.json();
            eventCenterState.events = data.events || [];
            eventCenterState.total = typeof data.total === "number" ? data.total : eventCenterState.events.length;
            eventCenterState.isLoading = false;

            if (DOM.eventTableSkeleton) DOM.eventTableSkeleton.style.display = "none";

            const hasActiveFilters = Boolean(
                (eventCenterState.currentTab && eventCenterState.currentTab !== "all") ||
                eventCenterState.filters.camera ||
                eventCenterState.filters.eventType ||
                eventCenterState.filters.targetId ||
                eventCenterState.filters.plate ||
                eventCenterState.filters.watchlistMatch ||
                eventCenterState.filters.notificationStatus ||
                eventCenterState.filters.fromTime ||
                eventCenterState.filters.toTime
            );

            if (eventCenterState.total === 0) {
                if (hasActiveFilters) {
                    if (DOM.eventFilterEmpty) DOM.eventFilterEmpty.style.display = "flex";
                } else {
                    if (DOM.eventTableEmpty) DOM.eventTableEmpty.style.display = "flex";
                }
                updateEventPagination(0, 1, eventCenterState.pageSize);
                return;
            }

            if (DOM.eventTableWrapper) DOM.eventTableWrapper.style.display = "block";
            renderEventTable(eventCenterState.events);
            updateEventPagination(eventCenterState.total, eventCenterState.page, eventCenterState.pageSize);

        } catch (err) {
            console.error("Lỗi khi tải danh sách sự kiện:", err);
            eventCenterState.isLoading = false;
            if (DOM.eventTableSkeleton) DOM.eventTableSkeleton.style.display = "none";
            if (DOM.eventTableError) {
                DOM.eventTableError.style.display = "flex";
                if (DOM.eventErrorMsg) {
                    DOM.eventErrorMsg.textContent = err.message || "Không thể kết nối tới dịch vụ Event Center.";
                }
            }
        }
    }

    /**
     * Render Events Table Rows. Missing values must display "--". Never invent metadata.
     */
    function renderEventTable(events) {
        if (!DOM.eventTableBody) return;

        if (!events || events.length === 0) {
            DOM.eventTableBody.innerHTML = "";
            return;
        }

        DOM.eventTableBody.innerHTML = events.map(ev => {
            const timeStr = ev.timestamp ? formatDateTime(ev.timestamp) : "--";
            const camId = ev.camera_id || "--";
            const evType = ev.event_type || "--";
            const objType = ev.object_type || "--";

            // Event type badge formatting
            let evTypeBadge = `<span class="event-type-badge ${escapeHtml(evType)}">${escapeHtml(evType.toUpperCase())}</span>`;
            if (evType === "face") evTypeBadge = `<span class="event-type-badge face">👤 Face</span>`;
            else if (evType === "plate") evTypeBadge = `<span class="event-type-badge plate">🔍 Plate</span>`;
            else if (evType === "vehicle") evTypeBadge = `<span class="event-type-badge vehicle">🚗 Vehicle</span>`;
            else if (evType === "passage") evTypeBadge = `<span class="event-type-badge passage">🛣️ Passage</span>`;
            else if (evType === "business") evTypeBadge = `<span class="event-type-badge business">💼 Business</span>`;

            // Target or Plate display
            let targetPlateHtml = "--";
            if (ev.plate) {
                targetPlateHtml = `<span class="license-plate-badge-sm font-mono font-semibold">${escapeHtml(ev.plate)}</span>`;
            } else if (ev.target_id) {
                targetPlateHtml = `<span class="font-mono text-muted" style="font-size:0.8rem;" title="${escapeHtml(ev.target_id)}">🎯 ${escapeHtml(ev.target_id.slice(0, 8))}...</span>`;
            }

            // Similarity or Confidence display
            let confidenceStr = "--";
            if (ev.similarity !== null && ev.similarity !== undefined) {
                confidenceStr = `${(Number(ev.similarity) * 100).toFixed(1)}%`;
            } else if (ev.confidence !== null && ev.confidence !== undefined) {
                confidenceStr = `${(Number(ev.confidence) * 100).toFixed(1)}%`;
            }

            // Watchlist match badge
            let matchHtml = `<span class="status-pill status-neutral">--</span>`;
            if (ev.watchlist_match === true) {
                matchHtml = `<span class="status-pill status-danger font-semibold">✓ MATCH</span>`;
            } else if (ev.watchlist_match === false) {
                matchHtml = `<span class="status-pill status-neutral">Không khớp</span>`;
            }

            // Notification status badge
            let noticeHtml = "--";
            if (ev.notification_status) {
                const s = ev.notification_status;
                if (s === "sent") noticeHtml = `<span class="status-pill status-active">✓ Đã gửi</span>`;
                else if (s === "pending") noticeHtml = `<span class="status-pill status-warning">⏳ Chờ gửi</span>`;
                else if (s === "failed") noticeHtml = `<span class="status-pill status-danger">✕ Thất bại</span>`;
                else if (s === "suppressed") noticeHtml = `<span class="status-pill status-neutral">Bị chặn</span>`;
                else noticeHtml = `<span class="status-pill status-neutral">${escapeHtml(s)}</span>`;
            }

            // Evidence button/thumbnail
            let evidenceHtml = `<span class="text-muted">--</span>`;
            if (ev.evidence && ev.evidence.url) {
                evidenceHtml = `
                    <button type="button" class="row-action-btn" title="Xem bằng chứng hình ảnh" onclick="window.dattOpenEventDetailDrawer('${escapeHtml(ev.event_id)}')">
                        🖼️
                    </button>
                `;
            }

            return `
                <tr data-event-id="${escapeHtml(ev.event_id)}">
                    <td>
                        <span class="font-mono text-muted" style="font-size: 0.8rem;">${escapeHtml(timeStr)}</span>
                    </td>
                    <td>
                        <span class="font-semibold text-highlight" style="font-size: 0.85rem;">📹 ${escapeHtml(camId)}</span>
                    </td>
                    <td>
                        ${evTypeBadge}
                    </td>
                    <td>
                        <span style="font-size: 0.83rem;">${escapeHtml(objType)}</span>
                    </td>
                    <td>
                        ${targetPlateHtml}
                    </td>
                    <td>
                        <span class="font-mono font-semibold" style="font-size: 0.85rem;">${escapeHtml(confidenceStr)}</span>
                    </td>
                    <td>
                        ${matchHtml}
                    </td>
                    <td>
                        ${noticeHtml}
                    </td>
                    <td style="text-align: center;">
                        ${evidenceHtml}
                    </td>
                    <td style="text-align: center;">
                        <button type="button" class="row-action-btn" title="Xem chi tiết sự kiện" onclick="window.dattOpenEventDetailDrawer('${escapeHtml(ev.event_id)}')">
                            👁️
                        </button>
                    </td>
                </tr>
            `;
        }).join("");
    }

    /**
     * Update Event Pagination Controls and Info.
     */
    function updateEventPagination(total, page, pageSize) {
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        const startIdx = total === 0 ? 0 : (page - 1) * pageSize + 1;
        const endIdx = Math.min(total, page * pageSize);

        if (DOM.eventPaginationInfo) {
            DOM.eventPaginationInfo.textContent = `Hiển thị ${startIdx} - ${endIdx} trong tổng số ${total} sự kiện`;
        }
        if (DOM.eventCurrentPageBadge) {
            DOM.eventCurrentPageBadge.textContent = `Trang ${page} / ${totalPages}`;
        }
        if (DOM.btnEventPrevPage) {
            DOM.btnEventPrevPage.disabled = (page <= 1);
        }
        if (DOM.btnEventNextPage) {
            DOM.btnEventNextPage.disabled = (page >= totalPages);
        }
    }

    /**
     * Open Event Detail Drawer and Fetch Full Event Data.
     * Evidence must use /api/event_center/events/{type}:{uuid}/evidence.
     */
    window.dattOpenEventDetailDrawer = async function(eventId) {
        if (!eventId) return;

        // Reset fields to --
        if (DOM.evDrawerTitle) DOM.evDrawerTitle.textContent = eventId;
        if (DOM.evDrawerIdSub) DOM.evDrawerIdSub.textContent = eventId;
        if (DOM.evDrawerId) DOM.evDrawerId.textContent = eventId;
        if (DOM.evDrawerBadgeType) DOM.evDrawerBadgeType.textContent = "EVENT PROFILE";
        if (DOM.evDrawerMatchPill) {
            DOM.evDrawerMatchPill.textContent = "--";
            DOM.evDrawerMatchPill.className = "status-pill";
        }
        if (DOM.evDrawerType) DOM.evDrawerType.textContent = "--";
        if (DOM.evDrawerTimestamp) DOM.evDrawerTimestamp.textContent = "--";
        if (DOM.evDrawerCamera) DOM.evDrawerCamera.textContent = "--";
        if (DOM.evDrawerObjectType) DOM.evDrawerObjectType.textContent = "--";
        if (DOM.evDrawerTarget) DOM.evDrawerTarget.textContent = "--";
        if (DOM.evDrawerPlate) DOM.evDrawerPlate.textContent = "--";
        if (DOM.evDrawerSimilarity) DOM.evDrawerSimilarity.textContent = "--";
        if (DOM.evDrawerConfidence) DOM.evDrawerConfidence.textContent = "--";
        if (DOM.evDrawerMatch) DOM.evDrawerMatch.textContent = "--";
        if (DOM.evDrawerNotification) DOM.evDrawerNotification.textContent = "--";
        if (DOM.evDrawerExtendedText) DOM.evDrawerExtendedText.textContent = "Đang tải dữ liệu...";

        // Evidence frame reset
        if (DOM.evDrawerEvidenceLoading) DOM.evDrawerEvidenceLoading.style.display = "flex";
        if (DOM.evDrawerEvidenceImg) {
            DOM.evDrawerEvidenceImg.style.display = "none";
            DOM.evDrawerEvidenceImg.src = "";
        }
        if (DOM.evDrawerEvidenceUnavailable) DOM.evDrawerEvidenceUnavailable.style.display = "none";
        if (DOM.evDrawerEvidenceStatusBadge) DOM.evDrawerEvidenceStatusBadge.textContent = "Đang tải...";

        if (DOM.drawerEventDetail) {
            DOM.drawerEventDetail.classList.add("open");
        }
        if (DOM.drawerBackdrop) {
            DOM.drawerBackdrop.style.display = "block";
        }

        try {
            const resp = await fetch(apiUrl(`/api/event_center/events/${encodeURIComponent(eventId)}`));
            if (!resp.ok) {
                throw new Error("Không thể tải chi tiết sự kiện từ API.");
            }
            const data = await resp.json();
            const ev = data.event || {};
            eventCenterState.selectedEvent = ev;

            // Populate metadata
            if (DOM.evDrawerTitle) DOM.evDrawerTitle.textContent = ev.event_id || eventId;
            if (DOM.evDrawerIdSub) DOM.evDrawerIdSub.textContent = ev.source_event_id || ev.event_id || "--";
            if (DOM.evDrawerId) DOM.evDrawerId.textContent = ev.event_id || "--";
            if (DOM.evDrawerBadgeType) DOM.evDrawerBadgeType.textContent = (ev.event_type || "EVENT").toUpperCase();
            
            if (DOM.evDrawerMatchPill) {
                if (ev.watchlist_match) {
                    DOM.evDrawerMatchPill.className = "status-pill status-danger font-semibold";
                    DOM.evDrawerMatchPill.textContent = "WATCHLIST MATCH";
                } else {
                    DOM.evDrawerMatchPill.className = "status-pill status-neutral";
                    DOM.evDrawerMatchPill.textContent = "NORMAL EVENT";
                }
            }

            if (DOM.evDrawerType) DOM.evDrawerType.textContent = ev.event_type || "--";
            if (DOM.evDrawerTimestamp) DOM.evDrawerTimestamp.textContent = ev.timestamp ? formatDateTime(ev.timestamp) : "--";
            if (DOM.evDrawerCamera) DOM.evDrawerCamera.textContent = ev.camera_id || "--";
            if (DOM.evDrawerObjectType) DOM.evDrawerObjectType.textContent = ev.object_type || "--";
            if (DOM.evDrawerTarget) DOM.evDrawerTarget.textContent = ev.target_id || "--";
            if (DOM.evDrawerPlate) DOM.evDrawerPlate.textContent = ev.plate || "--";
            if (DOM.evDrawerSimilarity) {
                DOM.evDrawerSimilarity.textContent = (ev.similarity !== null && ev.similarity !== undefined) 
                    ? `${(Number(ev.similarity) * 100).toFixed(1)}%` 
                    : "--";
            }
            if (DOM.evDrawerConfidence) {
                DOM.evDrawerConfidence.textContent = (ev.confidence !== null && ev.confidence !== undefined) 
                    ? `${(Number(ev.confidence) * 100).toFixed(1)}%` 
                    : "--";
            }
            if (DOM.evDrawerMatch) {
                DOM.evDrawerMatch.textContent = ev.watchlist_match ? "✓ Trùng khớp với Watchlist" : "Không trùng khớp Watchlist";
            }
            if (DOM.evDrawerNotification) {
                DOM.evDrawerNotification.textContent = ev.notification_status ? ev.notification_status.toUpperCase() : "--";
            }

            // Extended Metadata display
            if (DOM.evDrawerExtendedText) {
                if (ev.event_type === "passage") {
                    DOM.evDrawerExtendedText.textContent = `Lượt xe qua (Vehicle Passage): Biển số ${ev.plate || '--'}, Tin cậy: ${ev.confidence ? (Number(ev.confidence)*100).toFixed(1)+'%' : '--'}`;
                } else if (ev.event_type === "business") {
                    DOM.evDrawerExtendedText.textContent = `Sự kiện nghiệp vụ (Business Event): Biển số ${ev.plate || '--'}, Camera: ${ev.camera_id || '--'}`;
                } else if (ev.event_type === "face") {
                    DOM.evDrawerExtendedText.textContent = `Nhận diện khuôn mặt ArcFace: Target ${ev.target_id || 'Chưa định danh'}, Tương đồng: ${ev.similarity ? (Number(ev.similarity)*100).toFixed(1)+'%' : '--'}`;
                } else if (ev.event_type === "plate") {
                    DOM.evDrawerExtendedText.textContent = `Biển số phương tiện: ${ev.plate || '--'}, Watchlist Decision: ${ev.watchlist_match ? 'MATCH' : 'NO_MATCH'}`;
                } else {
                    DOM.evDrawerExtendedText.textContent = `Phương tiện: Camera ${ev.camera_id || '--'}, Đối tượng ${ev.object_type || '--'}`;
                }
            }

            // Evidence Loading: MUST use /api/event_center/events/{type}:{uuid}/evidence
            if (ev.evidence && ev.evidence.url) {
                const evidenceUrl = apiUrl(ev.evidence.url);
                if (DOM.evDrawerEvidenceImg) {
                    DOM.evDrawerEvidenceImg.onload = function() {
                        if (DOM.evDrawerEvidenceLoading) DOM.evDrawerEvidenceLoading.style.display = "none";
                        if (DOM.evDrawerEvidenceUnavailable) DOM.evDrawerEvidenceUnavailable.style.display = "none";
                        DOM.evDrawerEvidenceImg.style.display = "block";
                        if (DOM.evDrawerEvidenceStatusBadge) {
                            DOM.evDrawerEvidenceStatusBadge.textContent = "Bằng chứng đã xác thực";
                            DOM.evDrawerEvidenceStatusBadge.className = "count-pill";
                        }
                    };
                    DOM.evDrawerEvidenceImg.onerror = function() {
                        if (DOM.evDrawerEvidenceLoading) DOM.evDrawerEvidenceLoading.style.display = "none";
                        DOM.evDrawerEvidenceImg.style.display = "none";
                        if (DOM.evDrawerEvidenceUnavailable) DOM.evDrawerEvidenceUnavailable.style.display = "flex";
                        if (DOM.evDrawerEvidenceStatusBadge) {
                            DOM.evDrawerEvidenceStatusBadge.textContent = "Không khả dụng";
                            DOM.evDrawerEvidenceStatusBadge.className = "count-pill";
                        }
                    };
                    DOM.evDrawerEvidenceImg.src = evidenceUrl;
                }
            } else {
                if (DOM.evDrawerEvidenceLoading) DOM.evDrawerEvidenceLoading.style.display = "none";
                if (DOM.evDrawerEvidenceImg) DOM.evDrawerEvidenceImg.style.display = "none";
                if (DOM.evDrawerEvidenceUnavailable) DOM.evDrawerEvidenceUnavailable.style.display = "flex";
                if (DOM.evDrawerEvidenceStatusBadge) {
                    DOM.evDrawerEvidenceStatusBadge.textContent = "Không có bằng chứng";
                    DOM.evDrawerEvidenceStatusBadge.className = "count-pill";
                }
            }

        } catch (err) {
            console.warn("Lỗi tải chi tiết sự kiện:", err);
            if (DOM.evDrawerExtendedText) DOM.evDrawerExtendedText.textContent = `Lỗi: ${err.message}`;
            if (DOM.evDrawerEvidenceLoading) DOM.evDrawerEvidenceLoading.style.display = "none";
            if (DOM.evDrawerEvidenceUnavailable) DOM.evDrawerEvidenceUnavailable.style.display = "flex";
            if (DOM.evDrawerEvidenceStatusBadge) DOM.evDrawerEvidenceStatusBadge.textContent = "Lỗi kết nối";
        }
    };

    /**
     * Close Event Detail Drawer.
     */
    window.dattCloseEventDrawer = function() {
        if (DOM.drawerEventDetail) {
            DOM.drawerEventDetail.classList.remove("open");
        }
        if (DOM.evDrawerEvidenceImg) {
            DOM.evDrawerEvidenceImg.src = "";
            DOM.evDrawerEvidenceImg.style.display = "none";
        }
        if (DOM.drawerBackdrop) {
            DOM.drawerBackdrop.style.display = "none";
        }
    };

    /**
     * Bind Event Center Event Listeners.
     */
    function initEventCenterEvents() {
        // Tab buttons
        document.querySelectorAll(".event-tab-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                const tab = btn.getAttribute("data-tab");
                switchEventTab(tab);
            });
        });

        // Filter Apply
        if (DOM.btnApplyEventFilters) {
            DOM.btnApplyEventFilters.addEventListener("click", () => {
                eventCenterState.filters.camera = DOM.eventFilterCamera ? DOM.eventFilterCamera.value : "";
                eventCenterState.filters.eventType = DOM.eventFilterType ? DOM.eventFilterType.value : "";
                eventCenterState.filters.targetId = (DOM.eventFilterTarget ? DOM.eventFilterTarget.value : "").trim();
                eventCenterState.filters.plate = (DOM.eventFilterPlate ? DOM.eventFilterPlate.value : "").trim();
                eventCenterState.filters.watchlistMatch = DOM.eventFilterMatch ? DOM.eventFilterMatch.value : "";
                eventCenterState.filters.notificationStatus = DOM.eventFilterNotification ? DOM.eventFilterNotification.value : "";
                eventCenterState.filters.fromTime = DOM.eventFilterFromTime ? DOM.eventFilterFromTime.value : "";
                eventCenterState.filters.toTime = DOM.eventFilterToTime ? DOM.eventFilterToTime.value : "";

                eventCenterState.page = 1;
                loadEventCenterEvents();
            });
        }

        // Filter Clear
        if (DOM.btnClearEventFilters) {
            DOM.btnClearEventFilters.addEventListener("click", () => {
                if (DOM.eventFilterCamera) DOM.eventFilterCamera.value = "";
                if (DOM.eventFilterType) DOM.eventFilterType.value = "";
                if (DOM.eventFilterTarget) DOM.eventFilterTarget.value = "";
                if (DOM.eventFilterPlate) DOM.eventFilterPlate.value = "";
                if (DOM.eventFilterMatch) DOM.eventFilterMatch.value = "";
                if (DOM.eventFilterNotification) DOM.eventFilterNotification.value = "";
                if (DOM.eventFilterFromTime) DOM.eventFilterFromTime.value = "";
                if (DOM.eventFilterToTime) DOM.eventFilterToTime.value = "";

                eventCenterState.filters = {
                    camera: "",
                    eventType: "",
                    targetId: "",
                    plate: "",
                    watchlistMatch: "",
                    notificationStatus: "",
                    fromTime: "",
                    toTime: ""
                };
                eventCenterState.page = 1;
                loadEventCenterEvents();
            });
        }

        // Reset Filter Empty Button
        if (DOM.btnResetEventFilterEmpty) {
            DOM.btnResetEventFilterEmpty.addEventListener("click", () => {
                if (DOM.btnClearEventFilters) DOM.btnClearEventFilters.click();
            });
        }

        // Sort selector
        if (DOM.eventSortSelect) {
            DOM.eventSortSelect.addEventListener("change", (e) => {
                eventCenterState.sort = e.target.value;
                eventCenterState.page = 1;
                loadEventCenterEvents();
            });
        }

        // Pagination buttons
        if (DOM.btnEventPrevPage) {
            DOM.btnEventPrevPage.addEventListener("click", () => {
                if (eventCenterState.page > 1) {
                    eventCenterState.page -= 1;
                    loadEventCenterEvents();
                }
            });
        }
        if (DOM.btnEventNextPage) {
            DOM.btnEventNextPage.addEventListener("click", () => {
                const totalPages = Math.ceil(eventCenterState.total / eventCenterState.pageSize);
                if (eventCenterState.page < totalPages) {
                    eventCenterState.page += 1;
                    loadEventCenterEvents();
                }
            });
        }

        // Refresh & Retry
        if (DOM.btnRefreshEvents) {
            DOM.btnRefreshEvents.addEventListener("click", () => {
                loadEventCenterSummary();
                loadEventCenterEvents();
            });
        }
        if (DOM.btnRetryLoadEvents) {
            DOM.btnRetryLoadEvents.addEventListener("click", () => {
                loadEventCenterEvents();
            });
        }

        // Drawer Close
        if (DOM.btnCloseEventDrawer) {
            DOM.btnCloseEventDrawer.addEventListener("click", window.dattCloseEventDrawer);
        }
        if (DOM.btnCloseEventDrawerFooter) {
            DOM.btnCloseEventDrawerFooter.addEventListener("click", window.dattCloseEventDrawer);
        }
    }

    /**
     * Initial App Launch Sequence.
     */
    async function checkInitialAppState() {
        const urlParams = new URLSearchParams(window.location.search);
        const path = window.location.pathname;

        // Route: /cameras or /camera-management or query param
        if (path === "/cameras" || path === "/camera-management" || urlParams.has("camera_management") || urlParams.get("view") === "cameras") {
            setUiState(UI_STATE.CAMERA_MANAGEMENT);
            const forceEmpty = urlParams.get("empty") === "1" || urlParams.get("empty") === "true";
            if (forceEmpty) {
                setTimeout(() => {
                    loadManagementCameras(true);
                }, 100);
            }
            const modalType = urlParams.get("modal");
            const drawerType = urlParams.get("drawer");
            const targetId = urlParams.get("id");
            if (modalType === "add") {
                setTimeout(() => {
                    openAddCameraModal();
                }, 300);
            } else if (modalType === "edit") {
                setTimeout(() => {
                    const idToEdit = targetId || (cameraMgmtState.cameras[0] && cameraMgmtState.cameras[0].id) || "cam_01";
                    window.dattOpenEditCamModal(idToEdit);
                }, 400);
            } else if (modalType === "delete") {
                setTimeout(() => {
                    const idToDelete = targetId || (cameraMgmtState.cameras[0] && cameraMgmtState.cameras[0].id) || "cam_01";
                    window.dattOpenDeleteCamModal(idToDelete);
                }, 400);
            } else if (drawerType === "detail") {
                setTimeout(() => {
                    const idToView = targetId || (cameraMgmtState.cameras[0] && cameraMgmtState.cameras[0].id) || "cam_01";
                    window.dattOpenCamDrawer(idToView);
                }, 400);
            }
            return;
        }

        // Route: /watchlist or query param
        if (path === "/watchlist" || urlParams.has("watchlist") || urlParams.get("view") === "watchlist") {
            const initialTab = urlParams.get("type") === "vehicle" ? "vehicle" : "face";
            switchWatchlistTab(initialTab, false);
            setUiState(UI_STATE.WATCHLIST);

            // Auto-open drawer or modal if requested via URL query params
            const drawerType = urlParams.get("drawer");
            const drawerId = urlParams.get("id");
            const modalType = urlParams.get("modal");
            if (drawerType === "vehicle") {
                setTimeout(() => {
                    const targetId = drawerId || (watchlistState.vehicles[0] && watchlistState.vehicles[0].id);
                    if (targetId) window.dattOpenVehicleDrawer(targetId);
                }, 400);
            } else if (drawerType === "face") {
                setTimeout(() => {
                    const targetId = drawerId || (watchlistState.faces[0] && watchlistState.faces[0].id);
                    if (targetId) window.dattOpenFaceDrawer(targetId);
                }, 400);
            } else if (modalType === "add_vehicle") {
                setTimeout(() => {
                    resetAddVehicleForm();
                    if (DOM.modalAddVehicleWatchlist) DOM.modalAddVehicleWatchlist.style.display = "flex";
                }, 300);
            } else if (modalType === "add_face") {
                setTimeout(() => {
                    resetAddFaceForm();
                    if (DOM.modalAddFaceWatchlist) DOM.modalAddFaceWatchlist.style.display = "flex";
                }, 300);
            }
            return;
        }

        // Route: /events or query param
        if (path === "/events" || urlParams.has("events") || urlParams.get("view") === "events") {
            setUiState(UI_STATE.EVENT_CENTER);
            const tabParam = urlParams.get("tab");
            if (tabParam && ["all", "face", "plate", "vehicle", "passage", "business"].includes(tabParam)) {
                switchEventTab(tabParam);
            }
            const eventId = urlParams.get("id");
            if (eventId) {
                setTimeout(() => {
                    window.dattOpenEventDetailDrawer(eventId);
                }, 400);
            }
            return;
        }

        try {
            const resp = await fetch(apiUrl("/api/source_status"));
            if (resp.ok) {
                const data = await resp.json();
                if (data.is_ready && data.status === "RUNNING") {
                    setUiState(UI_STATE.MONITORING, {
                        name: (data.camera && data.camera.name) || "Live Camera",
                        provider: "System",
                        source_type: (data.camera && data.camera.type) || "Stream"
                    });
                    return;
                }
            }
        } catch (e) {}

        // Default: Open on Camera Selection
        setUiState(UI_STATE.SELECT_CAMERA);
    }

    /**
     * Application Initialization.
     */
    function init() {
        initTabs();
        initProviderSelector();
        initSearch();
        initDirectHlsTab();
        initYouTubeTab();
        initLocalVideoTab();
        initPreviewModal();
        initErrorActions();
        setupVideoStream();
        initAddPersonModal();
        initWatchlistEvents();
        initCameraManagementEvents();
        initEventCenterEvents();

        // Listen to browser history navigation
        window.addEventListener("popstate", () => {
            const p = window.location.pathname;
            const params = new URLSearchParams(window.location.search);
            if (p === "/watchlist") {
                const tab = params.get("type") === "vehicle" ? "vehicle" : "face";
                switchWatchlistTab(tab, false);
                setUiState(UI_STATE.WATCHLIST);
            } else if (p === "/cameras" || p === "/camera-management") {
                setUiState(UI_STATE.CAMERA_MANAGEMENT);
            } else if (p === "/events") {
                setUiState(UI_STATE.EVENT_CENTER);
            } else {
                checkInitialAppState();
            }
        });

        if (DOM.registerTargetBtn) {
            DOM.registerTargetBtn.addEventListener("click", registerTarget);
        }

        if (DOM.applySourceBtn) {
            DOM.applySourceBtn.addEventListener("click", () => {
                const sType = DOM.sourceTypeSelect ? DOM.sourceTypeSelect.value : "local";
                const sPath = DOM.sourceInput ? DOM.sourceInput.value.trim() : "";
                const sLoop = DOM.sourceLoopCheckbox ? DOM.sourceLoopCheckbox.checked : true;
                if (!sPath) {
                    if (DOM.sourceFeedback) {
                        DOM.sourceFeedback.className = "feedback-msg error";
                        DOM.sourceFeedback.textContent = "Vui lòng nhập đường dẫn tệp hoặc URL luồng.";
                    }
                    return;
                }
                if (DOM.sourceFeedback) DOM.sourceFeedback.textContent = "";
                const displayName = `Source: ${sPath.split(/[\\/]/).pop() || sPath}`;
                window.dattSelectCamera(displayName, sPath, sType, "Custom Source", null, sLoop);
            });
        }

        if (DOM.zoneToggleCheckbox) {
            DOM.zoneToggleCheckbox.addEventListener("change", async (e) => {
                const enabled = e.target.checked;
                try {
                    await fetch(apiUrl("/set_zone_mode"), {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ zone_enabled: enabled }),
                    });
                } catch (err) {
                    console.warn("Failed to set zone mode:", err);
                }
            });
        }

        loadTargets();
        loadVideoLibrary();
        checkInitialAppState();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
