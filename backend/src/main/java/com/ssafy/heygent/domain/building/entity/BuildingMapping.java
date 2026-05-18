package com.ssafy.heygent.domain.building.entity;

import com.ssafy.heygent.domain.user.entity.User;
import jakarta.persistence.*;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

/**
 * 건물 페이지의 층(floor) ↔ AI 세션(sessionId) 매핑.
 * 같은 (user_id, floor) 조합은 유일하다 — 한 사용자의 각 층에 단 하나의 세션만 매핑된다.
 */
@Entity
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
@AllArgsConstructor
@Builder
@Table(
        name = "building_mappings",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_building_mappings_user_floor", columnNames = {"user_id", "floor"})
        },
        indexes = {
                @Index(name = "idx_building_mappings_user_id", columnList = "user_id")
        }
)
@EntityListeners(AuditingEntityListener.class)
public class BuildingMapping {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    /**
     * 층 번호. 현재 1~3 사용.
     */
    @Column(nullable = false)
    private Integer floor;

    /**
     * AI 세션 ID (예: session_xxx). AI 서버 측 식별자 그대로 보관하며 FK 는 걸지 않는다.
     */
    @Column(name = "session_id", nullable = false, length = 100)
    private String sessionId;

    @CreatedDate
    @Column(updatable = false)
    private LocalDateTime createdAt;

    @LastModifiedDate
    private LocalDateTime updatedAt;

    public void updateSessionId(String sessionId) {
        this.sessionId = sessionId;
    }
}
