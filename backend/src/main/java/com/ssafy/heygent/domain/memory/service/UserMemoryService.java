package com.ssafy.heygent.domain.memory.service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import com.ssafy.heygent.domain.memory.dto.request.CreateMemoryCandidatesRequest;
import com.ssafy.heygent.domain.memory.dto.request.CreateMemoryRequest;
import com.ssafy.heygent.domain.memory.dto.request.MarkMemoryUsedRequest;
import com.ssafy.heygent.domain.memory.dto.response.UserMemoryEventResponse;
import com.ssafy.heygent.domain.memory.dto.response.UserMemoryResponse;
import com.ssafy.heygent.domain.memory.embedding.MemoryEmbeddingService;
import com.ssafy.heygent.domain.memory.entity.MemoryEventType;
import com.ssafy.heygent.domain.memory.entity.MemoryOperationType;
import com.ssafy.heygent.domain.memory.entity.MemoryScopeType;
import com.ssafy.heygent.domain.memory.entity.MemoryStatus;
import com.ssafy.heygent.domain.memory.entity.MemoryStoreType;
import com.ssafy.heygent.domain.memory.entity.MemoryType;
import com.ssafy.heygent.domain.memory.entity.UserMemory;
import com.ssafy.heygent.domain.memory.repository.UserMemoryRepository;
import com.ssafy.heygent.domain.memory.repository.UserMemoryVectorRepository;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;

import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class UserMemoryService {

    private static final double MIN_IMPORTANCE_TO_STORE = 0.5;
    private static final double MIN_CONFIDENCE_TO_STORE = 0.7;
    private static final int DEFAULT_RECALL_LIMIT = 5;
    private static final int MAX_RECALL_LIMIT = 20;
    private static final int RECALL_FALLBACK_CANDIDATE_SIZE = 100;
    private static final double MIN_RECALL_SIMILARITY = 0.35;
    private static final double MAX_RECALL_DISTANCE = 1.0 - MIN_RECALL_SIMILARITY;
    private static final double SEMANTIC_DUPLICATE_SIMILARITY = 0.92;
    private static final Set<String> ALLOWED_METADATA_CATEGORIES = Set.of(
        "preference",
        "profile",
        "fact",
        "instruction",
        "procedure",
        "event",
        "reason",
        "task_state"
    );

    private final UserMemoryRepository userMemoryRepository;
    private final UserMemoryVectorRepository userMemoryVectorRepository;
    private final MemoryEmbeddingService memoryEmbeddingService;
    private final MemorySafetyValidator memorySafetyValidator;
    private final UserMemoryEventService userMemoryEventService;

    @Transactional
    public UserMemoryResponse create(Long userId, CreateMemoryRequest request) {
        MemoryOperationType operationType = resolveOperationType(request.getOperationType());
        validateMemoryType(request.getMemoryType());
        validateMemoryScore(request.getImportance(), request.getConfidence());
        String normalizedContent = request.getContent().trim();
        Map<String, Object> metadata = normalizeMetadata(request.getMetadata(), request.getSourceSessionKey());
        memorySafetyValidator.validate(normalizedContent, request.getSummary(), metadata);
        memorySafetyValidator.validate(request.getEvidence(), request.getUpdateReason(), Map.of());
        MemoryStoreType storeType = resolveStoreType(request.getStoreType(), request.getMemoryType());
        MemoryScopeType scopeType = resolveScopeType(request.getScopeType(), storeType);
        validateStoreType(storeType, request.getMemoryType());
        validateSessionScope(scopeType, request.getExpiresAt());
        validateScopeMetadata(scopeType, metadata);
        validateValidityRange(request.getValidFrom(), request.getValidUntil());

        if (operationType == MemoryOperationType.INVALIDATE) {
            return invalidateTargetMemory(userId, request);
        }
        List<Double> embedding = memoryEmbeddingService.embed(buildEmbeddingText(
            storeType,
            request.getMemoryType(),
            scopeType,
            request.getSummary(),
            normalizedContent,
            request.getEvidence(),
            metadata
        ));
        if (operationType == MemoryOperationType.UPDATE || operationType == MemoryOperationType.MERGE) {
            return replaceTargetMemory(
                userId,
                request,
                storeType,
                scopeType,
                metadata,
                normalizedContent,
                embedding,
                resolveChangeEventType(operationType)
            );
        }

        Optional<UserMemory> duplicateMemory = userMemoryRepository.findDuplicateActiveMemory(
                userId,
                storeType,
                request.getMemoryType(),
                scopeType,
                normalizedContent,
                MemoryStatus.ACTIVE
            )
            .filter(memory -> isNotExpired(memory, LocalDateTime.now()));
        if (duplicateMemory.isPresent()) {
            return UserMemoryResponse.from(duplicateMemory.get());
        }

        return findSemanticDuplicateMemory(
                userId,
                storeType,
                request.getMemoryType(),
                scopeType,
                metadata,
                embedding
            )
            .map(UserMemoryResponse::from)
            .orElseGet(() -> saveMemory(
                userId,
                request,
                storeType,
                scopeType,
                metadata,
                normalizedContent,
                embedding,
                MemoryEventType.CREATED
            ));
    }

    @Transactional
    public List<UserMemoryResponse> createCandidates(Long userId, CreateMemoryCandidatesRequest request) {
        return createCandidates(userId, request.getCandidates());
    }

    @Transactional
    public List<UserMemoryResponse> createCandidates(Long userId, List<CreateMemoryRequest> candidates) {
        List<UserMemoryResponse> responses = new ArrayList<>();
        Set<Long> touchedTargetMemoryIds = new LinkedHashSet<>();

        for (CreateMemoryRequest candidate : candidates) {
            if (!isStorableScore(candidate.getImportance(), candidate.getConfidence())) {
                continue;
            }

            Set<Long> candidateTargetMemoryIds = targetChangingMemoryIds(candidate);
            if (!candidateTargetMemoryIds.isEmpty()
                && intersects(touchedTargetMemoryIds, candidateTargetMemoryIds)) {
                continue;
            }

            UserMemoryResponse response = create(userId, candidate);
            responses.add(response);
            touchedTargetMemoryIds.addAll(candidateTargetMemoryIds);
        }

        return responses;
    }

    private UserMemoryResponse saveMemory(
        Long userId,
        CreateMemoryRequest request,
        MemoryStoreType storeType,
        MemoryScopeType scopeType,
        Map<String, Object> metadata,
        String normalizedContent,
        List<Double> embedding,
        MemoryEventType eventType
    ) {

        UserMemory memory = UserMemory.builder()
            .userId(userId)
            .storeType(storeType)
            .memoryType(request.getMemoryType())
            .scopeType(scopeType)
            .content(normalizedContent)
            .summary(trimToNull(request.getSummary()))
            .metadata(metadata)
            .importance(request.getImportance())
            .confidence(request.getConfidence())
            .status(MemoryStatus.ACTIVE)
            .sourceSessionKey(trimToNull(request.getSourceSessionKey()))
            .sourceTaskRunId(trimToNull(request.getSourceTaskRunId()))
            .sourceMessageId(trimToNull(request.getSourceMessageId()))
            .evidence(trimToNull(request.getEvidence()))
            .updateReason(trimToNull(request.getUpdateReason()))
            .validFrom(resolveValidFrom(request.getValidFrom()))
            .validUntil(request.getValidUntil())
            .expiresAt(request.getExpiresAt())
            .build();

        UserMemory savedMemory = userMemoryRepository.save(memory);
        userMemoryVectorRepository.updateEmbedding(savedMemory.getId(), embedding);
        userMemoryEventService.record(savedMemory, eventType);
        return UserMemoryResponse.from(savedMemory);
    }

    public List<UserMemoryResponse> getMyMemories(Long userId) {
        LocalDateTime now = LocalDateTime.now();
        return userMemoryRepository.findByUserIdAndStatusOrderByImportanceDescCreatedAtDesc(
                userId,
                MemoryStatus.ACTIVE
            )
            .stream()
            .filter(memory -> isNotExpired(memory, now))
            .map(UserMemoryResponse::from)
            .toList();
    }

    public List<UserMemoryEventResponse> getMemoryEvents(Long userId, Long memoryId) {
        findOwnedMemory(userId, memoryId);
        return userMemoryEventService.findEvents(userId, memoryId).stream()
            .map(UserMemoryEventResponse::from)
            .toList();
    }

    @Transactional
    public List<UserMemoryResponse> recall(
        Long userId,
        Integer limit,
        String query,
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        String workspaceKey,
        String sessionKey,
        String resourceId,
        List<String> tags,
        List<String> metadataCategories
    ) {
        int normalizedLimit = normalizeRecallLimit(limit);
        List<String> normalizedMetadataCategories = normalizeMetadataCategories(metadataCategories);
        List<UserMemory> memories;

        if (StringUtils.hasText(query)) {
            memories = recallByEmbedding(
                userId,
                normalizedLimit,
                query,
                storeType,
                memoryType,
                scopeType,
                workspaceKey,
                sessionKey,
                resourceId,
                tags,
                normalizedMetadataCategories
            );
        } else {
            memories = recallByFilters(
                userId,
                normalizedLimit,
                storeType,
                memoryType,
                scopeType,
                workspaceKey,
                sessionKey,
                resourceId,
                tags,
                normalizedMetadataCategories
            );
        }

        LocalDateTime accessedAt = LocalDateTime.now();
        memories.forEach(memory -> {
            memory.markAccessed(accessedAt);
            userMemoryEventService.record(memory, MemoryEventType.RECALLED, null, Map.of(
                "queryProvided", StringUtils.hasText(query),
                "limit", normalizedLimit
            ));
        });

        return memories.stream()
            .map(UserMemoryResponse::from)
            .toList();
    }

    private List<UserMemory> recallByEmbedding(
        Long userId,
        int limit,
        String query,
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        String workspaceKey,
        String sessionKey,
        String resourceId,
        List<String> tags,
        List<String> metadataCategories
    ) {
        List<Double> queryEmbedding = memoryEmbeddingService.embed(query.trim());
        List<Long> memoryIds = userMemoryVectorRepository.searchIds(
            userId,
            queryEmbedding,
            storeType,
            memoryType,
            scopeType,
            workspaceKey,
            sessionKey,
            resourceId,
            tags,
            metadataCategories,
            MIN_CONFIDENCE_TO_STORE,
            MIN_IMPORTANCE_TO_STORE,
            MAX_RECALL_DISTANCE,
            limit
        );

        if (memoryIds.isEmpty()) {
            return recallByLocalEmbedding(
                userId,
                limit,
                queryEmbedding,
                storeType,
                memoryType,
                scopeType,
                workspaceKey,
                sessionKey,
                resourceId,
                tags,
                metadataCategories
            );
        }

        Map<Long, Integer> orderById = new LinkedHashMap<>();
        for (int i = 0; i < memoryIds.size(); i++) {
            orderById.put(memoryIds.get(i), i);
        }

        return userMemoryRepository.findAllById(memoryIds).stream()
            .sorted(Comparator.comparing(memory -> orderById.get(memory.getId())))
            .toList();
    }

    private List<UserMemory> recallByLocalEmbedding(
        Long userId,
        int limit,
        List<Double> queryEmbedding,
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        String workspaceKey,
        String sessionKey,
        String resourceId,
        List<String> tags,
        List<String> metadataCategories
    ) {
        List<ScoredMemory> scoredMemories = findRecallCandidates(userId, storeType, memoryType, scopeType).stream()
            .filter(memory -> matchesMetadata(memory, workspaceKey, sessionKey, resourceId, tags, metadataCategories))
            .filter(memory -> StringUtils.hasText(memory.getEmbeddingText()))
            .map(memory -> new ScoredMemory(
                memory,
                cosineSimilarity(queryEmbedding, parseEmbedding(memory.getEmbeddingText()))
            ))
            .filter(scoredMemory -> scoredMemory.score() >= MIN_RECALL_SIMILARITY)
            .sorted(Comparator
                .comparing(ScoredMemory::score)
                .thenComparing(scoredMemory -> scoredMemory.memory().getImportance())
                .reversed()
            )
            .limit(limit)
            .toList();

        return scoredMemories.stream()
            .map(ScoredMemory::memory)
            .toList();
    }

    private List<UserMemory> recallByFilters(
        Long userId,
        int limit,
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        String workspaceKey,
        String sessionKey,
        String resourceId,
        List<String> tags,
        List<String> metadataCategories
    ) {
        return findRecallCandidates(userId, storeType, memoryType, scopeType).stream()
            .filter(memory -> matchesMetadata(memory, workspaceKey, sessionKey, resourceId, tags, metadataCategories))
            .limit(limit)
            .toList();
    }

    private List<UserMemory> findRecallCandidates(
        Long userId,
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType
    ) {
        return userMemoryRepository.findRecallCandidates(
            userId,
            MemoryStatus.ACTIVE,
            MIN_CONFIDENCE_TO_STORE,
            MIN_IMPORTANCE_TO_STORE,
            LocalDateTime.now(),
            storeType,
            memoryType,
            scopeType,
            MemoryScopeType.SESSION,
            PageRequest.of(0, RECALL_FALLBACK_CANDIDATE_SIZE)
        );
    }

    @Transactional
    public void delete(Long userId, Long memoryId) {
        UserMemory memory = userMemoryRepository.findById(memoryId)
            .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));

        if (memory.getStatus() == MemoryStatus.DELETED) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }
        if (!memory.getUserId().equals(userId)) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }

        memory.delete();
        userMemoryEventService.record(memory, MemoryEventType.DELETED);
    }

    @Transactional
    public UserMemoryResponse markUsed(Long userId, Long memoryId, MarkMemoryUsedRequest request) {
        return markUsed(userId, memoryId, request.getUsefulnessScore());
    }

    @Transactional
    public UserMemoryResponse markUsed(Long userId, Long memoryId, Double usefulnessScore) {
        return markUsed(userId, memoryId, usefulnessScore, null);
    }

    @Transactional
    public UserMemoryResponse markUsed(
        Long userId,
        Long memoryId,
        Double usefulnessScore,
        String sourceTaskRunId
    ) {
        UserMemory memory = findOwnedMemory(userId, memoryId);
        if (memory.getStatus() != MemoryStatus.ACTIVE || !isNotExpired(memory, LocalDateTime.now())) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }

        String normalizedTaskRunId = trimToNull(sourceTaskRunId);
        if (userMemoryEventService.existsEvent(memory, MemoryEventType.USED, normalizedTaskRunId)) {
            return UserMemoryResponse.from(memory);
        }

        memory.markUsed(LocalDateTime.now(), usefulnessScore);
        userMemoryEventService.record(
            memory,
            MemoryEventType.USED,
            usefulnessScore,
            Map.of(),
            normalizedTaskRunId,
            null
        );
        return UserMemoryResponse.from(memory);
    }

    private UserMemoryResponse replaceTargetMemory(
        Long userId,
        CreateMemoryRequest request,
        MemoryStoreType storeType,
        MemoryScopeType scopeType,
        Map<String, Object> metadata,
        String normalizedContent,
        List<Double> embedding,
        MemoryEventType eventType
    ) {
        UserMemory targetMemory = findOwnedMemory(userId, request.getTargetMemoryId());
        validateTargetCanChange(targetMemory);
        List<UserMemory> additionalTargetMemories = findAdditionalTargetMemories(userId, request, targetMemory.getId());

        UserMemoryResponse savedResponse = saveMemory(
            userId,
            request,
            storeType,
            scopeType,
            metadata,
            normalizedContent,
            embedding,
            eventType
        );
        targetMemory.invalidate(savedResponse.getId(), trimToNull(request.getUpdateReason()), LocalDateTime.now());
        userMemoryEventService.record(targetMemory, MemoryEventType.INVALIDATED, null, Map.of(
            "supersededByMemoryId", savedResponse.getId(),
            "operationType", eventType.name()
        ));
        additionalTargetMemories.forEach(memory -> invalidateAdditionalTargetMemory(memory, savedResponse, request, eventType));
        return savedResponse;
    }

    private List<UserMemory> findAdditionalTargetMemories(Long userId, CreateMemoryRequest request, Long primaryTargetMemoryId) {
        List<Long> additionalTargetMemoryIds = request.getAdditionalTargetMemoryIds();
        if (additionalTargetMemoryIds == null || additionalTargetMemoryIds.isEmpty()) {
            return List.of();
        }

        LinkedHashSet<Long> uniqueTargetMemoryIds = additionalTargetMemoryIds.stream()
            .filter(Objects::nonNull)
            .filter(memoryId -> !memoryId.equals(primaryTargetMemoryId))
            .collect(LinkedHashSet::new, LinkedHashSet::add, LinkedHashSet::addAll);

        return uniqueTargetMemoryIds.stream()
            .map(memoryId -> {
                UserMemory memory = findOwnedMemory(userId, memoryId);
                validateTargetCanChange(memory);
                return memory;
            })
            .toList();
    }

    private void invalidateAdditionalTargetMemory(
        UserMemory memory,
        UserMemoryResponse savedResponse,
        CreateMemoryRequest request,
        MemoryEventType eventType
    ) {
        memory.invalidate(savedResponse.getId(), trimToNull(request.getUpdateReason()), LocalDateTime.now());
        userMemoryEventService.record(memory, MemoryEventType.INVALIDATED, null, Map.of(
            "supersededByMemoryId", savedResponse.getId(),
            "operationType", eventType.name(),
            "additionalTarget", true
        ));
    }

    private Optional<UserMemory> findSemanticDuplicateMemory(
        Long userId,
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        Map<String, Object> metadata,
        List<Double> embedding
    ) {
        return findRecallCandidates(userId, storeType, memoryType, scopeType).stream()
            .filter(memory -> hasSameMemoryBoundary(memory.getMetadata(), metadata))
            .filter(memory -> StringUtils.hasText(memory.getEmbeddingText()))
            .map(memory -> new ScoredMemory(
                memory,
                cosineSimilarity(embedding, parseEmbedding(memory.getEmbeddingText()))
            ))
            .filter(scoredMemory -> scoredMemory.score() >= SEMANTIC_DUPLICATE_SIMILARITY)
            .sorted(Comparator
                .comparing(ScoredMemory::score)
                .thenComparing(scoredMemory -> scoredMemory.memory().getImportance())
                .reversed()
            )
            .map(ScoredMemory::memory)
            .findFirst();
    }

    private boolean hasSameMemoryBoundary(Map<String, Object> storedMetadata, Map<String, Object> newMetadata) {
        return hasSameMetadataValue(storedMetadata, newMetadata, "workspaceKey")
            && hasSameMetadataValue(storedMetadata, newMetadata, "sessionKey")
            && hasSameMetadataValue(storedMetadata, newMetadata, "resourceId");
    }

    private boolean hasSameMetadataValue(Map<String, Object> storedMetadata, Map<String, Object> newMetadata, String key) {
        Object storedValue = storedMetadata == null ? null : storedMetadata.get(key);
        Object newValue = newMetadata == null ? null : newMetadata.get(key);
        if (storedValue == null && newValue == null) {
            return true;
        }
        if (storedValue == null || newValue == null) {
            return false;
        }
        return storedValue.toString().equals(newValue.toString());
    }

    private UserMemoryResponse invalidateTargetMemory(Long userId, CreateMemoryRequest request) {
        UserMemory targetMemory = findOwnedMemory(userId, request.getTargetMemoryId());
        validateTargetCanChange(targetMemory);
        targetMemory.invalidate(null, trimToNull(request.getUpdateReason()), LocalDateTime.now());
        userMemoryEventService.record(targetMemory, MemoryEventType.INVALIDATED);
        return UserMemoryResponse.from(targetMemory);
    }

    private UserMemory findOwnedMemory(Long userId, Long memoryId) {
        if (memoryId == null) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }

        UserMemory memory = userMemoryRepository.findById(memoryId)
            .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));

        if (!memory.getUserId().equals(userId)) {
            throw new CustomException(ErrorCode.ACCESS_DENIED);
        }
        return memory;
    }

    private void validateTargetCanChange(UserMemory memory) {
        if (memory.getStatus() == MemoryStatus.DELETED || memory.getStatus() == MemoryStatus.INACTIVE) {
            throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);
        }
    }

    private Set<Long> targetChangingMemoryIds(CreateMemoryRequest request) {
        MemoryOperationType operationType = resolveOperationType(request.getOperationType());
        if (operationType != MemoryOperationType.UPDATE
            && operationType != MemoryOperationType.MERGE
            && operationType != MemoryOperationType.INVALIDATE) {
            return Set.of();
        }

        LinkedHashSet<Long> targetMemoryIds = new LinkedHashSet<>();
        if (request.getTargetMemoryId() != null) {
            targetMemoryIds.add(request.getTargetMemoryId());
        }
        List<Long> additionalTargetMemoryIds = request.getAdditionalTargetMemoryIds();
        if (additionalTargetMemoryIds != null) {
            additionalTargetMemoryIds.stream()
                .filter(Objects::nonNull)
                .forEach(targetMemoryIds::add);
        }
        return targetMemoryIds;
    }

    private boolean intersects(Set<Long> left, Set<Long> right) {
        return right.stream().anyMatch(left::contains);
    }

    private void validateMemoryScore(Double importance, Double confidence) {
        if (!isStorableScore(importance, confidence)) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private boolean isStorableScore(Double importance, Double confidence) {
        return importance >= MIN_IMPORTANCE_TO_STORE && confidence >= MIN_CONFIDENCE_TO_STORE;
    }

    private MemoryOperationType resolveOperationType(MemoryOperationType operationType) {
        if (operationType == null) {
            return MemoryOperationType.ADD;
        }
        return operationType;
    }

    private MemoryEventType resolveChangeEventType(MemoryOperationType operationType) {
        if (operationType == MemoryOperationType.MERGE) {
            return MemoryEventType.MERGED;
        }
        return MemoryEventType.UPDATED;
    }

    private void validateMemoryType(MemoryType memoryType) {
        if (memoryType == MemoryType.PROJECT_CONTEXT) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private MemoryStoreType resolveStoreType(MemoryStoreType storeType, MemoryType memoryType) {
        if (storeType != null) {
            return storeType;
        }
        if (memoryType == MemoryType.PROFILE || memoryType == MemoryType.PREFERENCE) {
            return MemoryStoreType.USER_PROFILE;
        }
        return MemoryStoreType.AGENT_MEMORY;
    }

    private void validateStoreType(MemoryStoreType storeType, MemoryType memoryType) {
        if (storeType == MemoryStoreType.USER_PROFILE
            && memoryType != MemoryType.PROFILE
            && memoryType != MemoryType.PREFERENCE) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
        if (storeType == MemoryStoreType.AGENT_MEMORY
            && (memoryType == MemoryType.PROFILE || memoryType == MemoryType.PREFERENCE)) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private void validateSessionScope(MemoryScopeType scopeType, LocalDateTime expiresAt) {
        if (scopeType != MemoryScopeType.SESSION) {
            return;
        }
        if (expiresAt == null || !expiresAt.isAfter(LocalDateTime.now())) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private void validateScopeMetadata(MemoryScopeType scopeType, Map<String, Object> metadata) {
        if (scopeType == MemoryScopeType.WORKSPACE) {
            validateRequiredMetadata(metadata, "workspaceKey");
            return;
        }
        if (scopeType == MemoryScopeType.RESOURCE) {
            validateRequiredMetadata(metadata, "resourceId");
            return;
        }
        if (scopeType == MemoryScopeType.SESSION) {
            validateRequiredMetadata(metadata, "sessionKey");
        }
    }

    private void validateRequiredMetadata(Map<String, Object> metadata, String key) {
        if (metadata == null) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }

        Object value = metadata.get(key);
        if (value == null || !StringUtils.hasText(value.toString())) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private void validateValidityRange(LocalDateTime validFrom, LocalDateTime validUntil) {
        if (validFrom == null || validUntil == null) {
            return;
        }
        if (!validUntil.isAfter(validFrom)) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private int normalizeRecallLimit(Integer limit) {
        if (limit == null) {
            return DEFAULT_RECALL_LIMIT;
        }
        if (limit < 1) {
            return DEFAULT_RECALL_LIMIT;
        }
        return Math.min(limit, MAX_RECALL_LIMIT);
    }

    private MemoryScopeType resolveScopeType(MemoryScopeType scopeType, MemoryStoreType storeType) {
        if (scopeType == null) {
            return MemoryScopeType.GLOBAL;
        }
        return scopeType;
    }

    private Map<String, Object> normalizeMetadata(Map<String, Object> metadata, String sourceSessionKey) {
        Map<String, Object> normalizedMetadata = new LinkedHashMap<>();
        if (metadata != null && !metadata.isEmpty()) {
            normalizedMetadata.putAll(metadata);
        }
        if (StringUtils.hasText(sourceSessionKey) && !normalizedMetadata.containsKey("sessionKey")) {
            normalizedMetadata.put("sessionKey", sourceSessionKey.trim());
        }
        if (normalizedMetadata.isEmpty()) {
            return Map.of();
        }
        return normalizedMetadata;
    }

    private boolean matchesMetadata(
        UserMemory memory,
        String workspaceKey,
        String sessionKey,
        String resourceId,
        List<String> tags,
        List<String> metadataCategories
    ) {
        Map<String, Object> metadata = memory.getMetadata();
        if (!matchesMetadataValue(metadata, "workspaceKey", workspaceKey)) {
            return false;
        }
        if (!matchesMetadataValue(metadata, "sessionKey", sessionKey)) {
            return false;
        }
        if (!matchesMetadataValue(metadata, "resourceId", resourceId)) {
            return false;
        }
        return matchesTags(metadata, tags) && matchesMetadataCategories(metadata, metadataCategories);
    }

    private boolean matchesMetadataValue(Map<String, Object> metadata, String key, String expectedValue) {
        if (!StringUtils.hasText(expectedValue)) {
            return true;
        }
        if (metadata == null) {
            return false;
        }

        Object actualValue = metadata.get(key);
        return actualValue != null && expectedValue.trim().equals(actualValue.toString());
    }

    private boolean matchesTags(Map<String, Object> metadata, List<String> tags) {
        List<String> normalizedTags = tags == null ? List.of() : tags.stream()
            .filter(StringUtils::hasText)
            .map(String::trim)
            .toList();

        if (normalizedTags.isEmpty()) {
            return true;
        }
        if (metadata == null || !(metadata.get("tags") instanceof List<?> storedTags)) {
            return false;
        }

        List<String> normalizedStoredTags = storedTags.stream()
            .filter(Objects::nonNull)
            .map(Object::toString)
            .toList();

        return normalizedTags.stream().anyMatch(normalizedStoredTags::contains);
    }

    private boolean matchesMetadataCategories(Map<String, Object> metadata, List<String> metadataCategories) {
        List<String> normalizedCategories = normalizeMetadataCategories(metadataCategories);
        if (normalizedCategories.isEmpty()) {
            return true;
        }
        if (metadata == null) {
            return false;
        }
        Object category = metadata.get("category");
        return category != null && normalizedCategories.contains(category.toString().trim());
    }

    private List<String> normalizeMetadataCategories(List<String> metadataCategories) {
        if (metadataCategories == null) {
            return List.of();
        }
        return metadataCategories.stream()
            .filter(StringUtils::hasText)
            .map(category -> category.trim().toLowerCase().replace("-", "_"))
            .peek(this::validateMetadataCategory)
            .distinct()
            .toList();
    }

    private void validateMetadataCategory(String category) {
        if (!ALLOWED_METADATA_CATEGORIES.contains(category)) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private boolean isNotExpired(UserMemory memory, LocalDateTime now) {
        return isCurrentlyValid(memory, now) && (memory.getExpiresAt() == null || memory.getExpiresAt().isAfter(now));
    }

    private boolean isCurrentlyValid(UserMemory memory, LocalDateTime now) {
        boolean started = memory.getValidFrom() == null || !memory.getValidFrom().isAfter(now);
        boolean notEnded = memory.getValidUntil() == null || memory.getValidUntil().isAfter(now);
        return started && notEnded;
    }

    private String buildEmbeddingText(UserMemory memory) {
        return buildEmbeddingText(
            memory.getStoreType(),
            memory.getMemoryType(),
            memory.getScopeType(),
            memory.getSummary(),
            memory.getContent(),
            memory.getEvidence(),
            memory.getMetadata()
        );
    }

    private String buildEmbeddingText(
        MemoryStoreType storeType,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        String summary,
        String content,
        String evidence,
        Map<String, Object> metadata
    ) {
        return String.join(
            "\n",
            storeType.name(),
            memoryType.name(),
            scopeType.name(),
            nullToEmpty(summary),
            content,
            nullToEmpty(evidence),
            metadata == null ? "" : metadata.toString()
        );
    }

    private LocalDateTime resolveValidFrom(LocalDateTime validFrom) {
        if (validFrom == null) {
            return LocalDateTime.now();
        }
        return validFrom;
    }

    private List<Double> parseEmbedding(String embeddingText) {
        String trimmedText = embeddingText.replace("[", "").replace("]", "");
        if (!StringUtils.hasText(trimmedText)) {
            return List.of();
        }

        return List.of(trimmedText.split(",")).stream()
            .map(String::trim)
            .filter(StringUtils::hasText)
            .map(Double::parseDouble)
            .toList();
    }

    private double cosineSimilarity(List<Double> left, List<Double> right) {
        if (left.isEmpty() || right.isEmpty() || left.size() != right.size()) {
            return 0.0;
        }

        double dotProduct = 0.0;
        double leftNorm = 0.0;
        double rightNorm = 0.0;

        for (int i = 0; i < left.size(); i++) {
            double leftValue = left.get(i);
            double rightValue = right.get(i);
            dotProduct += leftValue * rightValue;
            leftNorm += leftValue * leftValue;
            rightNorm += rightValue * rightValue;
        }

        if (leftNorm == 0.0 || rightNorm == 0.0) {
            return 0.0;
        }
        return dotProduct / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
    }

    private record ScoredMemory(UserMemory memory, double score) {
    }

    private String nullToEmpty(String value) {
        if (value == null) {
            return "";
        }
        return value;
    }

    private String trimToNull(String value) {
        if (!StringUtils.hasText(value)) {
            return null;
        }
        return value.trim();
    }
}
