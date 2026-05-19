package com.ssafy.heygent.domain.building.service;

import com.ssafy.heygent.domain.building.dto.response.BuildingMappingResponse;
import com.ssafy.heygent.domain.building.entity.BuildingMapping;
import com.ssafy.heygent.domain.building.repository.BuildingMappingRepository;
import com.ssafy.heygent.domain.user.entity.User;
import com.ssafy.heygent.domain.user.repository.UserRepository;
import com.ssafy.heygent.global.exception.CustomException;
import com.ssafy.heygent.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class BuildingMappingService {

    private static final int MIN_FLOOR = 1;
    private static final int MAX_FLOOR = 3;

    private final BuildingMappingRepository repository;
    private final UserRepository userRepository;

    public List<BuildingMappingResponse> listMyMappings(Long userId) {
        User user = findUser(userId);
        return repository.findAllByUser(user).stream()
                .map(BuildingMappingResponse::from)
                .toList();
    }

    @Transactional
    public BuildingMappingResponse assignFloor(Long userId, Integer floor, String sessionId) {
        validateFloor(floor);
        User user = findUser(userId);
        BuildingMapping mapping = repository.findByUserAndFloor(user, floor)
                .map(existing -> {
                    existing.updateSessionId(sessionId);
                    return existing;
                })
                .orElseGet(() -> BuildingMapping.builder()
                        .user(user)
                        .floor(floor)
                        .sessionId(sessionId)
                        .build());
        BuildingMapping saved = repository.save(mapping);
        return BuildingMappingResponse.from(saved);
    }

    @Transactional
    public void clearFloor(Long userId, Integer floor) {
        validateFloor(floor);
        User user = findUser(userId);
        repository.deleteByUserAndFloor(user, floor);
    }

    /**
     * 특정 세션이 삭제될 때 모든 사용자의 매핑에서 해당 세션을 일괄 제거한다.
     * AI 세션 삭제 흐름에서 호출.
     */
    @Transactional
    public int clearAllMappingsBySessionId(String sessionId) {
        return repository.deleteAllBySessionId(sessionId);
    }

    private void validateFloor(Integer floor) {
        if (floor == null || floor < MIN_FLOOR || floor > MAX_FLOOR) {
            throw new CustomException(ErrorCode.INVALID_INPUT_VALUE);
        }
    }

    private User findUser(Long userId) {
        return userRepository.findById(userId)
                .orElseThrow(() -> new CustomException(ErrorCode.RESOURCE_NOT_FOUND));
    }
}
