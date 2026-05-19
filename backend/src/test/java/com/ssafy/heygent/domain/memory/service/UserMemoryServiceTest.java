package com.ssafy.heygent.domain.memory.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Pageable;
import org.springframework.test.util.ReflectionTestUtils;

import com.ssafy.heygent.domain.memory.dto.request.CreateMemoryRequest;
import com.ssafy.heygent.domain.memory.dto.response.UserMemoryResponse;
import com.ssafy.heygent.domain.memory.embedding.MemoryEmbeddingService;
import com.ssafy.heygent.domain.memory.entity.MemoryOperationType;
import com.ssafy.heygent.domain.memory.entity.MemoryScopeType;
import com.ssafy.heygent.domain.memory.entity.MemoryStatus;
import com.ssafy.heygent.domain.memory.entity.MemoryStoreType;
import com.ssafy.heygent.domain.memory.entity.MemoryType;
import com.ssafy.heygent.domain.memory.entity.UserMemory;
import com.ssafy.heygent.domain.memory.repository.UserMemoryRepository;
import com.ssafy.heygent.domain.memory.repository.UserMemoryVectorRepository;
import com.ssafy.heygent.global.exception.CustomException;

@ExtendWith(MockitoExtension.class)
class UserMemoryServiceTest {

    private static final Long USER_ID = 1L;

    @Mock
    private UserMemoryRepository userMemoryRepository;

    @Mock
    private UserMemoryVectorRepository userMemoryVectorRepository;

    @Mock
    private MemoryEmbeddingService memoryEmbeddingService;

    @Mock
    private MemorySafetyValidator memorySafetyValidator;

    @Mock
    private UserMemoryEventService userMemoryEventService;

    @InjectMocks
    private UserMemoryService userMemoryService;

    @Test
    void createWorkspaceMemoryWithoutWorkspaceKeyFails() {
        CreateMemoryRequest request = createRequest(MemoryType.FACT, MemoryScopeType.WORKSPACE);

        assertThatThrownBy(() -> userMemoryService.create(USER_ID, request))
            .isInstanceOf(CustomException.class);

        verify(memoryEmbeddingService, never()).embed(anyString());
        verify(userMemoryRepository, never()).save(any(UserMemory.class));
    }

    @Test
    void createReturnsSemanticDuplicateMemoryWhenSimilarityIsHigh() {
        CreateMemoryRequest request = createRequest(MemoryType.FACT, MemoryScopeType.GLOBAL);
        UserMemory existingMemory = memory(10L, MemoryType.FACT, MemoryScopeType.GLOBAL, "[1.0,0.0]");

        when(memoryEmbeddingService.embed(anyString())).thenReturn(List.of(1.0, 0.0));
        when(userMemoryRepository.findDuplicateActiveMemory(
            eq(USER_ID),
            eq(MemoryStoreType.AGENT_MEMORY),
            eq(MemoryType.FACT),
            eq(MemoryScopeType.GLOBAL),
            eq("사용자는 회의록을 짧게 요약하는 것을 선호한다."),
            eq(MemoryStatus.ACTIVE)
        )).thenReturn(Optional.empty());
        when(userMemoryRepository.findRecallCandidates(
            eq(USER_ID),
            eq(MemoryStatus.ACTIVE),
            anyDouble(),
            anyDouble(),
            any(LocalDateTime.class),
            eq(MemoryStoreType.AGENT_MEMORY),
            eq(MemoryType.FACT),
            eq(MemoryScopeType.GLOBAL),
            eq(MemoryScopeType.SESSION),
            any(Pageable.class)
        )).thenReturn(List.of(existingMemory));

        UserMemoryResponse response = userMemoryService.create(USER_ID, request);

        assertThat(response.getId()).isEqualTo(10L);
        verify(userMemoryRepository, never()).save(any(UserMemory.class));
        verify(userMemoryVectorRepository, never()).updateEmbedding(any(), any());
    }

    @Test
    void recallWithQueryDoesNotFallbackToFilterWhenSimilarityIsLow() {
        UserMemory unrelatedMemory = memory(20L, MemoryType.FACT, MemoryScopeType.GLOBAL, "[1.0,0.0]");

        when(memoryEmbeddingService.embed("프론트엔드 기술 선택")).thenReturn(List.of(0.0, 1.0));
        when(userMemoryVectorRepository.searchIds(
            eq(USER_ID),
            eq(List.of(0.0, 1.0)),
            isNull(),
            isNull(),
            isNull(),
            isNull(),
            isNull(),
            isNull(),
            isNull(),
            eq(List.of()),
            anyDouble(),
            anyDouble(),
            anyDouble(),
            eq(5)
        )).thenReturn(List.of());
        when(userMemoryRepository.findRecallCandidates(
            eq(USER_ID),
            eq(MemoryStatus.ACTIVE),
            anyDouble(),
            anyDouble(),
            any(LocalDateTime.class),
            isNull(),
            isNull(),
            isNull(),
            eq(MemoryScopeType.SESSION),
            any(Pageable.class)
        )).thenReturn(List.of(unrelatedMemory));

        List<UserMemoryResponse> responses = userMemoryService.recall(
            USER_ID,
            5,
            "프론트엔드 기술 선택",
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null
        );

        assertThat(responses).isEmpty();
        assertThat(unrelatedMemory.getAccessCount()).isZero();
    }

    @Test
    void recallByFiltersAppliesMetadataCategoryFilter() {
        UserMemory matchingMemory = memory(30L, MemoryType.FACT, MemoryScopeType.GLOBAL, "[1.0,0.0]");
        UserMemory otherMemory = memory(31L, MemoryType.FACT, MemoryScopeType.GLOBAL, "[1.0,0.0]");
        ReflectionTestUtils.setField(matchingMemory, "metadata", Map.of("category", "task_state"));
        ReflectionTestUtils.setField(otherMemory, "metadata", Map.of("category", "preference"));
        when(userMemoryRepository.findRecallCandidates(
            eq(USER_ID),
            eq(MemoryStatus.ACTIVE),
            anyDouble(),
            anyDouble(),
            any(LocalDateTime.class),
            isNull(),
            isNull(),
            isNull(),
            eq(MemoryScopeType.SESSION),
            any(Pageable.class)
        )).thenReturn(List.of(matchingMemory, otherMemory));

        List<UserMemoryResponse> responses = userMemoryService.recall(
            USER_ID,
            5,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            List.of("task_state")
        );

        assertThat(responses)
            .extracting(UserMemoryResponse::getId)
            .containsExactly(30L);
    }

    @Test
    void createCandidatesSkipsLaterUpdateWithSameTargetMemory() {
        CreateMemoryRequest firstRequest = createUpdateRequest(10L, List.of(), "사용자는 점심으로 샐러드를 선호한다.");
        CreateMemoryRequest secondRequest = createUpdateRequest(10L, List.of(), "사용자는 점심으로 생선을 선호한다.");
        UserMemory targetMemory = preferenceMemory(10L, "사용자는 점심으로 고기를 선호한다.");
        UserMemory savedMemory = preferenceMemory(100L, "사용자는 점심으로 샐러드를 선호한다.");

        when(memoryEmbeddingService.embed(anyString())).thenReturn(List.of(1.0, 0.0));
        when(userMemoryRepository.findById(10L)).thenReturn(Optional.of(targetMemory));
        when(userMemoryRepository.save(any(UserMemory.class))).thenReturn(savedMemory);

        List<UserMemoryResponse> responses = userMemoryService.createCandidates(
            USER_ID,
            List.of(firstRequest, secondRequest)
        );

        assertThat(responses)
            .extracting(UserMemoryResponse::getId)
            .containsExactly(100L);
        assertThat(targetMemory.getStatus()).isEqualTo(MemoryStatus.INACTIVE);
        verify(userMemoryRepository).findById(10L);
        verify(userMemoryRepository).save(any(UserMemory.class));
    }

    @Test
    void createCandidatesSkipsLaterUpdateOverlappingAdditionalTargetMemory() {
        CreateMemoryRequest firstRequest = createUpdateRequest(10L, List.of(11L), "사용자는 점심으로 샐러드를 선호한다.");
        CreateMemoryRequest secondRequest = createUpdateRequest(11L, List.of(), "사용자는 점심으로 생선을 선호한다.");
        UserMemory primaryTargetMemory = preferenceMemory(10L, "사용자는 점심으로 고기를 선호한다.");
        UserMemory additionalTargetMemory = preferenceMemory(11L, "사용자는 점심으로 든든한 고기 메뉴를 선호한다.");
        UserMemory savedMemory = preferenceMemory(101L, "사용자는 점심으로 샐러드를 선호한다.");

        when(memoryEmbeddingService.embed(anyString())).thenReturn(List.of(1.0, 0.0));
        when(userMemoryRepository.findById(10L)).thenReturn(Optional.of(primaryTargetMemory));
        when(userMemoryRepository.findById(11L)).thenReturn(Optional.of(additionalTargetMemory));
        when(userMemoryRepository.save(any(UserMemory.class))).thenReturn(savedMemory);

        List<UserMemoryResponse> responses = userMemoryService.createCandidates(
            USER_ID,
            List.of(firstRequest, secondRequest)
        );

        assertThat(responses)
            .extracting(UserMemoryResponse::getId)
            .containsExactly(101L);
        assertThat(primaryTargetMemory.getStatus()).isEqualTo(MemoryStatus.INACTIVE);
        assertThat(additionalTargetMemory.getStatus()).isEqualTo(MemoryStatus.INACTIVE);
        verify(userMemoryRepository).findById(10L);
        verify(userMemoryRepository).findById(11L);
        verify(userMemoryRepository).save(any(UserMemory.class));
    }

    private CreateMemoryRequest createRequest(MemoryType memoryType, MemoryScopeType scopeType) {
        CreateMemoryRequest request = new CreateMemoryRequest();
        ReflectionTestUtils.setField(request, "memoryType", memoryType);
        ReflectionTestUtils.setField(request, "scopeType", scopeType);
        ReflectionTestUtils.setField(request, "content", "사용자는 회의록을 짧게 요약하는 것을 선호한다.");
        ReflectionTestUtils.setField(request, "summary", "짧은 회의록 요약 선호");
        ReflectionTestUtils.setField(request, "metadata", Map.of());
        ReflectionTestUtils.setField(request, "importance", 0.8);
        ReflectionTestUtils.setField(request, "confidence", 0.9);
        return request;
    }

    private CreateMemoryRequest createUpdateRequest(Long targetMemoryId, List<Long> additionalTargetMemoryIds, String content) {
        CreateMemoryRequest request = createRequest(MemoryType.PREFERENCE, MemoryScopeType.GLOBAL);
        ReflectionTestUtils.setField(request, "operationType", MemoryOperationType.UPDATE);
        ReflectionTestUtils.setField(request, "storeType", MemoryStoreType.USER_PROFILE);
        ReflectionTestUtils.setField(request, "targetMemoryId", targetMemoryId);
        ReflectionTestUtils.setField(request, "additionalTargetMemoryIds", additionalTargetMemoryIds);
        ReflectionTestUtils.setField(request, "content", content);
        ReflectionTestUtils.setField(request, "summary", "점심 선호");
        ReflectionTestUtils.setField(request, "updateReason", "사용자 발화 기준 선호 변경");
        return request;
    }

    private UserMemory memory(
        Long id,
        MemoryType memoryType,
        MemoryScopeType scopeType,
        String embeddingText
    ) {
        return UserMemory.builder()
            .id(id)
            .userId(USER_ID)
            .storeType(MemoryStoreType.AGENT_MEMORY)
            .memoryType(memoryType)
            .scopeType(scopeType)
            .content("사용자는 회의록을 짧게 요약하는 것을 선호한다.")
            .summary("짧은 회의록 요약 선호")
            .metadata(Map.of())
            .embeddingText(embeddingText)
            .importance(0.8)
            .confidence(0.9)
            .status(MemoryStatus.ACTIVE)
            .accessCount(0L)
            .usedCount(0L)
            .usefulnessScore(0.0)
            .build();
    }

    private UserMemory preferenceMemory(Long id, String content) {
        return UserMemory.builder()
            .id(id)
            .userId(USER_ID)
            .storeType(MemoryStoreType.USER_PROFILE)
            .memoryType(MemoryType.PREFERENCE)
            .scopeType(MemoryScopeType.GLOBAL)
            .content(content)
            .summary("점심 선호")
            .metadata(Map.of())
            .embeddingText("[1.0,0.0]")
            .importance(0.8)
            .confidence(0.9)
            .status(MemoryStatus.ACTIVE)
            .accessCount(0L)
            .usedCount(0L)
            .usefulnessScore(0.0)
            .build();
    }
}
