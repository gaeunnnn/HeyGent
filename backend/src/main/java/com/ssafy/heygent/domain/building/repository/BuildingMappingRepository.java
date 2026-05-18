package com.ssafy.heygent.domain.building.repository;

import com.ssafy.heygent.domain.building.entity.BuildingMapping;
import com.ssafy.heygent.domain.user.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface BuildingMappingRepository extends JpaRepository<BuildingMapping, Long> {

    List<BuildingMapping> findAllByUser(User user);

    Optional<BuildingMapping> findByUserAndFloor(User user, Integer floor);

    void deleteByUserAndFloor(User user, Integer floor);

    /**
     * 세션이 삭제되면 그 세션과 매핑된 층을 모두 비운다.
     * AI 세션 ID 기준 일괄 삭제 — 사용자 무관(여러 사용자가 같은 세션을 매핑하지 않는 게 일반적이지만 방어적으로).
     */
    @Modifying
    @Query("delete from BuildingMapping bm where bm.sessionId = :sessionId")
    int deleteAllBySessionId(@Param("sessionId") String sessionId);
}
